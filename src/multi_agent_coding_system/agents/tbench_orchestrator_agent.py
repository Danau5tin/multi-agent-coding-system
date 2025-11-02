"""Terminal Bench specific Orchestrator Agent implementation."""

import asyncio
import logging
import time
from pathlib import Path
from typing import List, Tuple

import litellm


from terminal_bench.agents.base_agent import AgentResult, BaseAgent
from terminal_bench.agents.failure_mode import FailureMode
from terminal_bench.terminal.tmux_session import TmuxSession

from multi_agent_coding_system.agents.orchestrator_agent import OrchestratorAgent
from multi_agent_coding_system.agents.orchestrator_agent_stateful import OrchestratorAgentStateful
from multi_agent_coding_system.agents.env_interaction.command_executor import DockerExecutor
from multi_agent_coding_system.agents.utils.llm_client import count_input_tokens, count_output_tokens

logger = logging.getLogger(__name__)


class TBenchOrchestratorAgent(OrchestratorAgent, BaseAgent):
    """Terminal Bench specific implementation of the Orchestrator Agent (stateless mode)."""

    @staticmethod
    def name() -> str:
        return "TBenchOrchestratorAgent"
    
    def perform_task(
        self,
        instruction: str,
        session: TmuxSession,
        logging_dir: Path | None = None,
    ) -> AgentResult:
        """Execute the orchestrator task using the stateless execution pattern.

        This is the Terminal Bench specific entry point.

        Args:
            instruction: The task instruction to execute
            session: TmuxSession containing the container
            logging_dir: Optional directory for logging

        Returns:
            AgentResult with execution details
        """
        # Get container name from session
        container_name = session.container.name
        if not container_name:
            raise ValueError("Container name is required for DockerExecutor")

        # Set up logging
        timestamped_markers: List[Tuple[float, str]] = []

        # Create docker executor for this session
        docker_executor = DockerExecutor(container_name=container_name)

        # Generate session ID for logging
        time_dd_mm_yyyy_hh_mm_ss = time.strftime("%d_%m_%Y_%H_%M_%S", time.localtime())
        session_id = f"tbench_{time_dd_mm_yyyy_hh_mm_ss}"

        # Setup the orchestrator with the docker executor and logging directory
        log_dir = Path("./session_logs")
        self.setup(docker_executor, log_dir, session_id)

        failure_mode = FailureMode.NONE
        total_input_tokens = 0
        total_output_tokens = 0

        try:
            # Run the orchestrator using asyncio
            result = asyncio.run(self.run(instruction, max_turns=50))
            
            # Calculate total tokens from all subagent executions
            subagent_input_tokens = 0
            subagent_output_tokens = 0
            
            # Iterate through conversation history to find all subagent trajectories
            if self.conversation_history and self.conversation_history.turns:
                for turn in self.conversation_history.turns:
                    if turn.subagent_trajectories:
                        for task_id, trajectory_data in turn.subagent_trajectories.items():
                            subagent_input_tokens += trajectory_data.get('total_input_tokens', 0)
                            subagent_output_tokens += trajectory_data.get('total_output_tokens', 0)
                            logger.info(f"Subagent {task_id} tokens - Input: {trajectory_data.get('total_input_tokens', 0)}, Output: {trajectory_data.get('total_output_tokens', 0)}")
            
            # Calculate orchestrator's own token usage
            orchestrator_input_tokens = count_input_tokens(self.orchestrator_messages, self.model)
            orchestrator_output_tokens = count_output_tokens(self.orchestrator_messages, self.model)
            
            # Add orchestrator's own token usage
            total_input_tokens = subagent_input_tokens + orchestrator_input_tokens
            total_output_tokens = subagent_output_tokens + orchestrator_output_tokens
            
            logger.info(f"Orchestrator tokens - Input: {orchestrator_input_tokens}, Output: {orchestrator_output_tokens}")
            logger.info(f"Total tokens (orchestrator + subagents) - Input: {total_input_tokens}, Output: {total_output_tokens}")
            
            # Determine failure mode based on result
            if result['completed']:
                failure_mode = FailureMode.NONE
            elif result['max_turns_reached']:
                failure_mode = FailureMode.AGENT_TIMEOUT
            else:
                failure_mode = FailureMode.UNKNOWN_AGENT_ERROR
                
        except Exception as e:
            logger.exception(f"Error during orchestrator execution: {e}")
            failure_mode = FailureMode.UNKNOWN_AGENT_ERROR

        return AgentResult(
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            failure_mode=failure_mode,
            timestamped_markers=timestamped_markers,
        )


class TBenchOrchestratorAgentStateful(OrchestratorAgentStateful, BaseAgent):
    """Terminal Bench specific implementation of the Orchestrator Agent (stateful mode - accumulates message history)."""

    @staticmethod
    def name() -> str:
        return "TBenchOrchestratorAgentStateful"

    def perform_task(
        self,
        instruction: str,
        session: TmuxSession,
        logging_dir: Path | None = None,
    ) -> AgentResult:
        """Execute the orchestrator task using stateful execution (accumulates full message history).

        This is the Terminal Bench specific entry point.

        Args:
            instruction: The task instruction to execute
            session: TmuxSession containing the container
            logging_dir: Optional directory for logging

        Returns:
            AgentResult with execution details
        """
        # Get container name from session
        container_name = session.container.name
        if not container_name:
            raise ValueError("Container name is required for DockerExecutor")

        # Set up logging
        timestamped_markers: List[Tuple[float, str]] = []

        # Create docker executor for this session
        docker_executor = DockerExecutor(container_name=container_name)

        # Generate session ID for logging
        time_dd_mm_yyyy_hh_mm_ss = time.strftime("%d_%m_%Y_%H_%M_%S", time.localtime())
        session_id = f"tbench_stateful_{time_dd_mm_yyyy_hh_mm_ss}"

        # Setup the orchestrator with the docker executor and logging directory
        log_dir = Path("./session_logs")
        self.setup(docker_executor, log_dir, session_id)

        failure_mode = FailureMode.NONE
        total_input_tokens = 0
        total_output_tokens = 0

        try:
            # Run the orchestrator using asyncio
            result = asyncio.run(self.run(instruction, max_turns=50))

            # Calculate total tokens from all subagent executions
            subagent_input_tokens = 0
            subagent_output_tokens = 0

            # Iterate through conversation history to find all subagent trajectories
            if self.conversation_history and self.conversation_history.turns:
                for turn in self.conversation_history.turns:
                    if turn.subagent_trajectories:
                        for task_id, trajectory_data in turn.subagent_trajectories.items():
                            subagent_input_tokens += trajectory_data.get('total_input_tokens', 0)
                            subagent_output_tokens += trajectory_data.get('total_output_tokens', 0)
                            logger.info(f"Subagent {task_id} tokens - Input: {trajectory_data.get('total_input_tokens', 0)}, Output: {trajectory_data.get('total_output_tokens', 0)}")

            # Calculate orchestrator's own token usage from accumulated messages
            orchestrator_input_tokens = count_input_tokens(self.messages, self.model)
            orchestrator_output_tokens = count_output_tokens(self.messages, self.model)

            # Add orchestrator's own token usage
            total_input_tokens = subagent_input_tokens + orchestrator_input_tokens
            total_output_tokens = subagent_output_tokens + orchestrator_output_tokens

            logger.info(f"Orchestrator tokens - Input: {orchestrator_input_tokens}, Output: {orchestrator_output_tokens}")
            logger.info(f"Total tokens (orchestrator + subagents) - Input: {total_input_tokens}, Output: {total_output_tokens}")

            # Determine failure mode based on result
            if result['completed']:
                failure_mode = FailureMode.NONE
            elif result['max_turns_reached']:
                failure_mode = FailureMode.AGENT_TIMEOUT
            else:
                failure_mode = FailureMode.UNKNOWN_AGENT_ERROR

        except Exception as e:
            logger.exception(f"Error during orchestrator execution: {e}")
            failure_mode = FailureMode.UNKNOWN_AGENT_ERROR

        return AgentResult(
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            failure_mode=failure_mode,
            timestamped_markers=timestamped_markers,
        )
    