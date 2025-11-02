"""Stateful Orchestrator Agent - accumulates message history like RL rollouts."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, List
import time

from multi_agent_coding_system.agents.env_interaction.env_info_retriever import EnvInfoRetriever
from multi_agent_coding_system.agents.utils.time_utils import format_elapsed_time_with_prefix
from multi_agent_coding_system.agents.actions.hierarchical_task_manager import HierarchicalTaskManager
from multi_agent_coding_system.misc.session_logger import SessionLogger, AgentType

from multi_agent_coding_system.agents.actions.orchestrator_hub import OrchestratorHub
from multi_agent_coding_system.agents.actions.parsing.action_handler import ActionHandler
from multi_agent_coding_system.agents.actions.state_managers import ScratchpadManager, TodoManager
from multi_agent_coding_system.agents.env_interaction.entities.conversation_history import ConversationHistory
from multi_agent_coding_system.agents.env_interaction.entities.turn import Turn
from multi_agent_coding_system.agents.env_interaction.turn_executor import TurnExecutor
from multi_agent_coding_system.agents.actions.parsing.parser import SimpleActionParser

from multi_agent_coding_system.agents.utils.llm_client import (
    get_llm_response,
)
from multi_agent_coding_system.agents.state.orchestrator_state import OrchestratorState
from multi_agent_coding_system.agents.env_interaction.command_executor import CommandExecutor
from multi_agent_coding_system.misc.log_setup import setup_file_logging
from multi_agent_coding_system.agents.system_msgs.system_msg_loader import load_orchestrator_system_message

logger = logging.getLogger(__name__)
setup_file_logging("INFO")


class OrchestratorAgentStateful:
    """Stateful orchestrator that accumulates full message history (like RL training)."""

    def __init__(
        self,
        system_message_path: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        **kwargs
    ):
        """Initialize the orchestrator.

        Args:
            system_message_path: Path to system message file
            model: LiteLLM model to use (overrides env var)
            temperature: Temperature for LLM (overrides env var)
            api_key: API key for LiteLLM (overrides env var)
            api_base: API base URL for LiteLLM (overrides env var)
        """
        # Generate unique orchestrator ID
        import uuid
        self.agent_id = f"orca-{str(uuid.uuid4())[:8]}"

        # Store LLM configuration
        self.model = model or os.getenv("ORCA_ORCHESTRATOR_MODEL") or os.getenv("LITELLM_MODEL")
        self.api_key = api_key or os.getenv("ORCA_ORCHESTRATOR_API_KEY") or os.getenv("LITE_LLM_API_KEY")
        self.api_base = api_base or os.getenv("ORCA_ORCHESTRATOR_API_BASE") or os.getenv("LITE_LLM_API_BASE")
        self.temperature = temperature or float(os.getenv("ORCA_ORCHESTRATOR_TEMPERATURE", "0.1"))

        logger.info(f"OrchestratorAgentStateful initialized with model={self.model}, temperature={temperature}")

        # Load system message
        self.system_message = load_orchestrator_system_message()

        # These will be initialized in setup()
        self.orchestrator_hub = None
        self.conversation_history = None
        self.action_parser = None
        self.action_handler = None
        self.executor = None
        self.state = None

        # Accumulating message history (like RL rollout)
        self.messages: List[Dict[str, str]] = []

        # Session logger (will be initialized in setup or run)
        self.session_logger = None
        self.logging_dir = None

        # Track task start time
        self.task_start_time = None

    def setup(self, command_executor: CommandExecutor, logging_dir: Optional[Path] = None, session_id: Optional[str] = None):
        """Setup the orchestrator with the necessary components.

        Args:
            command_executor: The command executor to use
            logging_dir: Optional directory for logging
            session_id: Optional session ID for the logger
        """

        # Initialize components with the provided executor
        task_manager = HierarchicalTaskManager()
        self.orchestrator_hub = OrchestratorHub(
            agent_id=self.agent_id,
            task_manager=task_manager
        )
        self.conversation_history = ConversationHistory()

        # Store logging directory
        self.logging_dir = logging_dir

        # Initialize session logger if logging directory is provided
        self.session_logger = None
        if logging_dir:
            session_id = session_id or f"orca_{self.agent_id}_{int(time.time())}"
            self.session_logger = SessionLogger(
                logging_dir=logging_dir,
                session_id=session_id,
                agent_type=AgentType.ORCHESTRATOR
            )

        self.cmd_executor = command_executor

        self.action_parser = SimpleActionParser()
        self.action_handler = ActionHandler(
            executor=command_executor,
            todo_manager=TodoManager(),
            scratchpad_manager=ScratchpadManager(),
            orchestrator_hub=self.orchestrator_hub,
            logging_dir=logging_dir,
            depth=0,
            parent_agent_id=self.agent_id,
            session_logger=self.session_logger,
            verbose_outputs=True  # Key difference: verbose outputs for stateful mode
        )

        self.executor = TurnExecutor(
            action_parser=self.action_parser,
            action_handler=self.action_handler,
        )

        # Track state
        self.state = OrchestratorState(
            orchestrator_hub=self.orchestrator_hub,
            conversation_history=self.conversation_history
        )

    async def execute_turn(self) -> Dict[str, Any]:
        """Execute a single turn with stateful message accumulation."""
        if not self.executor or not self.state or not self.cmd_executor or not self.conversation_history:
            raise ValueError("OrchestratorAgentStateful not properly set up. Call setup() before executing turns.")

        llm_response = await self._get_llm_response()
        self.messages.append({"role": "assistant", "content": llm_response})

        result = await self.executor.execute(llm_response)
        env_response_text = "\n\n".join(result.env_responses) if result.env_responses else ""

        elapsed_str = format_elapsed_time_with_prefix(self.task_start_time)
        content = f"{env_response_text}\n\n{elapsed_str}"
        self.messages.append({"role": "user", "content": content})

        turn = Turn(
            llm_output=llm_response,
            actions_executed=result.actions_executed,
            env_responses=result.env_responses,
            subagent_trajectories=result.subagent_trajectories
        )

        # Add to conversation history
        self.conversation_history.add_turn(turn)

        # Log this turn if session logger is available
        if self.session_logger:
            # Get action names
            action_names = [type(action).__name__ for action in result.actions_executed]

            await self.session_logger.update_turn(
                llm_output=llm_response,
                env_response=env_response_text,
                actions=action_names,
                metadata={
                    "done": result.done,
                    "finish_message": result.finish_message,
                    "has_error": result.has_error
                }
            )

            await self.session_logger.end_turn()

        # Update done state
        if result.done:
            self.state.done = True
            self.state.finish_message = result.finish_message

        return {
            'done': result.done,
            'finish_message': result.finish_message,
            'has_error': result.has_error,
            'actions_executed': len(result.actions_executed),
            'turn': turn
        }

    async def _get_llm_response(self) -> str:
        """Get LLM response using accumulated message history."""
        # Call centralized LLM client with full message history
        response = await get_llm_response(
            messages=self.messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=4096,
            api_key=self.api_key,
            api_base=self.api_base
        )

        return response

    async def run(self, instruction: str, max_turns: int = 50) -> Dict[str, Any]:
        """Run the orchestrator until completion or max turns.

        Args:
            instruction: The main task to complete
            max_turns: Maximum number of turns before stopping

        Returns:
            Final execution summary
        """
        if not self.state or not self.cmd_executor:
            raise ValueError("OrchestratorAgentStateful not properly set up. Call setup() before running.")
        
        self.task_start_time = time.time()
        turns_executed = 0

        env_info_retriever = EnvInfoRetriever(self.cmd_executor)
        env_context = await env_info_retriever.run_and_format(title="Initial Env State")
        user_message = f"## Current Task\n{instruction}\n\n{env_context}"
        first_user_msg = {"role": "user", "content": user_message}
        self.messages = [
            {"role": "system", "content": self.system_message},
            first_user_msg
        ]

        # Start session if logger exists
        if self.session_logger:
            await self.session_logger.start_session(
                task=instruction,
                metadata={
                    "max_turns": max_turns,
                    "agent_id": self.agent_id,
                    "model": self.model,
                    "temperature": self.temperature,
                    "mode": "stateful"
                }
            )

        while not self.state.done and turns_executed < max_turns:
            turns_executed += 1

            if self.session_logger:
                await self.session_logger.start_turn(turns_executed)

            try:
                result = await self.execute_turn()
                if result['done']:
                    break

            except Exception as e:
                logger.error(f"Error in turn {turns_executed}: {e}")
                # Log error to session if available
                if self.session_logger:
                    await self.session_logger.update_turn(
                        metadata={"error": str(e)}
                    )
                    await self.session_logger.end_turn()

        # End the session
        if self.session_logger:
            finish_reason = "completed" if self.state.done else "max_turns_reached"
            await self.session_logger.end_session(reason=finish_reason)

        return {
            'completed': self.state.done,
            'finish_message': self.state.finish_message,
            'turns_executed': turns_executed,
            'max_turns_reached': turns_executed >= max_turns
        }
