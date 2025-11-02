"""Core Orchestrator Agent logic."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import uuid
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


class OrchestratorAgent:
    """Core orchestrator agent coordinating tasks and subagents."""
        
    def __init__(
        self,
        system_message_path: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        **kwargs  # Accept additional keyword arguments from terminal bench
    ):
        """Initialize the orchestrator.

        Args:
            system_message_path: Path to system message file
            model: LiteLLM model to use (overrides env var)
            temperature: Temperature for LLM (overrides env var)
            api_key: API key for LiteLLM (overrides env var)
            api_base: API base URL for LiteLLM (overrides env var)
        """
        # Generate unique orchestrator ID using centralized generator
        self.agent_id = f"orca-{str(uuid.uuid4())[:8]}"

        # Store LLM configuration
        self.model = model or os.getenv("ORCA_ORCHESTRATOR_MODEL") or os.getenv("LITELLM_MODEL")
        self.api_key = api_key or os.getenv("ORCA_ORCHESTRATOR_API_KEY") or os.getenv("LITE_LLM_API_KEY")
        self.api_base = api_base or os.getenv("ORCA_ORCHESTRATOR_API_BASE") or os.getenv("LITE_LLM_API_BASE")
        self.temperature = temperature or float(os.getenv("ORCA_ORCHESTRATOR_TEMPERATURE", "0.1"))
        
        logger.info(f"OrchestratorAgent initialized with model={self.model}, temperature={temperature}")
        
        # Load system message
        self.system_message = self._load_system_message(system_message_path)
        
        # These will be initialized in setup()
        self.orchestrator_hub = None
        self.conversation_history = None
        self.action_parser = None
        self.action_handler = None
        self.executor = None
        self.state = None
        
        # Track orchestrator's messages for token counting
        self.orchestrator_messages = []

        # Session logger (will be initialized in setup or run)
        self.session_logger = None
        self.logging_dir = None

        # Track task start time
        self.task_start_time = None
    
    def _load_system_message(self, path: Optional[str]) -> str:
        if path:
            # If explicit path provided, load from that file
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            # Use default system message loader
            return load_orchestrator_system_message()
    
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
        
        # Create action components
        self.action_parser = SimpleActionParser()
        self.action_handler = ActionHandler(
            executor=command_executor,
            todo_manager=TodoManager(),
            scratchpad_manager=ScratchpadManager(),
            orchestrator_hub=self.orchestrator_hub,
            logging_dir=logging_dir,  # Pass logging dir for subagent logging
            depth=0,  # Orchestrator is depth 0
            parent_agent_id=self.agent_id,
            session_logger=self.session_logger  # Pass the session logger directly
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

    async def execute_turn(self, instruction: str, turn_num: int) -> Dict[str, Any]:
        if not self.executor or not self.state or not self.cmd_executor:
            raise ValueError("OrchestratorAgent not properly set up. Call setup() before executing turns.")

        # Build user message with current state
        env_info_retriever = EnvInfoRetriever(self.cmd_executor)
        env_context = await env_info_retriever.run_and_format(title="Env State")
        elapsed_str = format_elapsed_time_with_prefix(self.task_start_time)
        user_message = f"## Current Task\n{instruction}\n\n{elapsed_str}\n\n{self.state.to_prompt()}\n\n{env_context}"
        
        # Get LLM response
        llm_response = await self._get_llm_response(user_message)

        # Execute actions from LLM response
        result = await self.executor.execute(llm_response)
        
        # Create turn for history
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

            # Create environment response text
            env_response_text = "\n".join(result.env_responses) if result.env_responses else ""

            await self.session_logger.update_turn(
                llm_output=llm_response,
                env_response=env_response_text,
                actions=action_names,
                metadata={
                    "instruction": instruction,
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
    
    async def _get_llm_response(self, user_message: str) -> str:
        # Build messages for this request
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message}
        ]
        
        # Track messages for token counting (add system message only once)
        if not self.orchestrator_messages:
            self.orchestrator_messages.append({"role": "system", "content": self.system_message})
        self.orchestrator_messages.append({"role": "user", "content": user_message})
        
        # Call centralized LLM client
        response = await get_llm_response(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=4096,
            api_key=self.api_key,
            api_base=self.api_base
        )
        
        # Track assistant response
        self.orchestrator_messages.append({"role": "assistant", "content": response})
        
        return response
    
    async def run(self, instruction: str, max_turns: int = 50) -> Dict[str, Any]:
        """Run the orchestrator until completion or max turns.

        Args:
            instruction: The main task to complete
            max_turns: Maximum number of turns before stopping

        Returns:
            Final execution summary
        """
        self.task_start_time = time.time()
        turns_executed = 0

        # Start session if logger exists
        if self.session_logger:
            await self.session_logger.start_session(
                task=instruction,
                metadata={
                    "max_turns": max_turns,
                    "agent_id": self.agent_id,
                    "model": self.model,
                    "temperature": self.temperature
                }
            )

        while not self.state.done and turns_executed < max_turns:
            turns_executed += 1

            # Start a new turn in session logger
            if self.session_logger:
                await self.session_logger.start_turn(turns_executed)

            try:
                result = await self.execute_turn(instruction, turns_executed)

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
    
