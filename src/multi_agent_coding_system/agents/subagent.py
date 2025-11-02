"""Subagent implementation for executing delegated tasks."""

import os
import logging
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path

from litellm.exceptions import ContextWindowExceededError

from multi_agent_coding_system.agents.actions.orchestrator_hub import OrchestratorHub
from multi_agent_coding_system.agents.actions.parsing.action_handler import ActionHandler
from multi_agent_coding_system.agents.actions.state_managers import ScratchpadManager, TodoManager
from multi_agent_coding_system.agents.actions.parsing.parser import SimpleActionParser
from multi_agent_coding_system.agents.env_interaction.command_executor import CommandExecutor
from multi_agent_coding_system.agents.actions.entities.actions import ReportAction
from multi_agent_coding_system.agents.actions.entities.subagent_report import ContextItem, SubagentMeta, SubagentReport
from multi_agent_coding_system.agents.env_interaction.turn_executor import TurnExecutor
from multi_agent_coding_system.agents.env_interaction.env_info_retriever import EnvInfoRetriever
from multi_agent_coding_system.agents.utils.llm_client import count_input_tokens, count_output_tokens, get_llm_response
from multi_agent_coding_system.agents.system_msgs.system_msg_loader import load_coder_system_message, load_explorer_system_message


logger = logging.getLogger(__name__)


@dataclass
class SubagentTask:
    """Task specification for a subagent."""
    agent_type: str  # "explorer" or "coder"
    title: str
    description: str
    max_turns: int
    ctx_store_ctxts: Dict[str, str]  # Resolved context content from store
    bootstrap_ctxts: List[Dict[str, str]]  # List of {"path": str, "content": str, "reason": str}


class Subagent:
    """Executes a specific task delegated by the orchestrator."""
    
    def __init__(
        self,
        agent_id: str,
        task: SubagentTask,
        executor: CommandExecutor,
        orchestrator_hub: OrchestratorHub,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        logging_dir: Optional[Path] = None,
        task_id: Optional[str] = None,
        depth: int = 1,
        max_consecutive_parse_errors: int = 3,
        session_tracker: Optional[Any] = None,
        max_execution_time_seconds: Optional[float] = None,
    ):
        """Initialize the subagent.

        Args:
            task: The task specification (includes max_turns)
            executor: Command executor (shared with orchestrator)
            task_manager: Task manager (shared with orchestrator)
            orchestrator_hub: Orchestrator hub for context access (shared with orchestrator)
            model: LiteLLM model to use (overrides env var)
            temperature: Temperature for LLM (overrides env var)
            api_key: API key for LiteLLM (overrides env var)
            api_base: API base URL for LiteLLM (overrides env var)
            logging_dir: Optional directory for logging turns
            task_id: Optional task ID for log file naming
            depth: Current agent depth for recursion control
            max_consecutive_parse_errors: Maximum consecutive parsing errors before forcing report
            max_execution_time_seconds: Maximum execution time in seconds before forcing report
        """
        self.agent_id = agent_id
        self.task = task
        self.executor = executor  # Store the executor for env info retrieval
        self.max_turns = task.max_turns
        self.depth = depth
        self.max_consecutive_parse_errors = max_consecutive_parse_errors
        self.consecutive_parse_errors = 0
        self.consecutive_no_actions = 0  # Track consecutive turns with no actions
        self.session_tracker = session_tracker  # Session tracker for logging turns
        self.max_execution_time_seconds = max_execution_time_seconds
        self.start_time: Optional[float] = None

        # Environment response truncation (prevent inference server overload)
        # Using ~4 chars per token heuristic: 3k tokens ≈ 12k chars
        self.max_env_response_chars = int(os.getenv("ORCA_MAX_ENV_RESPONSE_CHARS", "12000"))

        # Store LLM configuration
        self.model = model or os.getenv("ORCA_SUBAGENT_MODEL") or os.getenv("LITELLM_MODEL")
        self.api_key = api_key or os.getenv("ORCA_SUBAGENT_API_KEY") or os.getenv("LITE_LLM_API_KEY")
        self.api_base = api_base or os.getenv("ORCA_SUBAGENT_API_BASE") or os.getenv("LITE_LLM_API_BASE")
        self.temperature = temperature or float(os.getenv("ORCA_SUBAGENT_TEMPERATURE", "0.1"))
        
        # Initialize components (own state, shared executor)
        self.action_parser = SimpleActionParser()
        
        self.action_handler = ActionHandler(
            executor=executor,
            todo_manager=TodoManager(),
            scratchpad_manager=ScratchpadManager(),
            orchestrator_hub=orchestrator_hub,  # Pass the shared orchestrator hub
            logging_dir=logging_dir,
            depth=self.depth,  # Pass depth for recursion control
            parent_agent_id=self.agent_id
        )
        
        self.turn_exec = TurnExecutor(
            action_parser=self.action_parser,
            action_handler=self.action_handler
        )
        
        # Load system message based on agent type
        self.system_message = self._load_system_message()
        
        # Track completion
        self.report: Optional[SubagentReport] = None
        self.messages: List[Dict[str, str]] = []

    def _load_system_message(self) -> str:
        if self.task.agent_type == "explorer":
            return load_explorer_system_message(depth=self.depth)
        
        if self.task.agent_type == "coder":
            return load_coder_system_message(depth=self.depth)
        
        raise ValueError(f"Unknown agent type: {self.task.agent_type}")
        
    def _build_task_prompt(self) -> str:
        """Build the initial task prompt with all context."""
        sections = []

        # Task description
        sections.append(f"# Task: {self.task.title}\n")
        sections.append(f"{self.task.description}\n")

        # Include turn limit information
        sections.append("## Turn Limit\n")
        sections.append(f"You have a maximum of {self.max_turns} turns to complete this task.\n")

        # Include resolved contexts
        if self.task.ctx_store_ctxts:
            sections.append("## Provided Context\n")
            for ctx_id, content in self.task.ctx_store_ctxts.items():
                sections.append(f"### Context: {ctx_id}\n")
                sections.append(f"{content}\n")

        # Include bootstrap files/dirs
        if self.task.bootstrap_ctxts:
            sections.append("## Relevant Files/Directories\n")
            for item in self.task.bootstrap_ctxts:
                sections.append(f"- {item['path']}: {item['reason']}\n")

        sections.append("\nBegin your investigation/implementation now.")

        return "\n".join(sections)
    
    async def _get_llm_response(self, messages: List[Dict[str, str]]) -> str:
        """Get response from LLM using centralized client."""
        response = await get_llm_response(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=2000,
            api_key=self.api_key,
            api_base=self.api_base,
            debug=self.agent_id,
        )
        return response
    
    @property
    def total_input_tokens(self) -> int:
        """Calculate total input tokens from all messages."""
        return count_input_tokens(self.messages, self.model)
    
    @property
    def total_output_tokens(self) -> int:
        """Calculate total output tokens from all messages."""
        return count_output_tokens(self.messages, self.model)
    
    def _check_for_report(self, actions: List) -> Optional[SubagentReport]:
        """Check if any action is a ReportAction and convert to SubagentReport."""
        for action in actions:
            if isinstance(action, ReportAction):
                # Convert to SubagentReport
                contexts = [
                    ContextItem(id=ctx["id"], content=ctx["content"])
                    for ctx in action.contexts
                ]
                return SubagentReport(
                    contexts=contexts,
                    context_refs=action.context_refs if action.context_refs else [],  # Include context references
                    comments=action.comments,
                    meta=SubagentMeta(
                        trajectory=self.messages.copy() if hasattr(self, 'messages') else None,
                        total_input_tokens=0,  # Will be set in run()
                        total_output_tokens=0  # Will be set in run()
                    )
                )
        return None
    
    def _set_report_metadata(self, report: SubagentReport, turn_num: int) -> None:
        """Set metadata for a report."""
        report.meta.num_turns = turn_num
        report.meta.total_input_tokens = self.total_input_tokens
        report.meta.total_output_tokens = self.total_output_tokens
    
    def _append_to_last_user_message(self, content: str) -> None:
        """Append content to the last user message or create a new one."""
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages[-1]["content"] += content
        else:
            self.messages.append({"role": "user", "content": content.strip()})

    def _truncate_env_response(self, env_response: str) -> str:
        """Truncate environment response if it exceeds the character limit.

        Args:
            env_response: The environment response to potentially truncate

        Returns:
            Truncated response with notice if applicable, or original if within limits
        """
        if len(env_response) <= self.max_env_response_chars:
            return env_response

        # Truncate and add notice
        truncated = env_response[:self.max_env_response_chars]
        original_len = len(env_response)
        estimated_tokens = original_len // 4
        shown_tokens = self.max_env_response_chars // 4

        notice = (
            f"\n\n{'='*60}\n"
            f"⚠️ RESPONSE TRUNCATED ⚠️\n"
            f"Original length: ~{estimated_tokens:,} tokens ({original_len:,} chars)\n"
            f"Showing: ~{shown_tokens:,} tokens ({self.max_env_response_chars:,} chars)\n"
            f"{'='*60}"
        )

        return truncated + notice
    
    def _generate_force_message(self, reason_type: str, consecutive_errors: int = 0, elapsed_time: float = 0) -> str:
        """Generate a force report message based on the reason type."""
        if reason_type == "parsing_errors":
            return (
                "\n\n⚠️ CRITICAL: MAXIMUM CONSECUTIVE PARSING ERRORS REACHED ⚠️\n"
                f"You have had {consecutive_errors} consecutive turns with parsing errors.\n"
                "Your action syntax is repeatedly malformed.\n\n"
                "You MUST now submit a report using ONLY the <report> action.\n"
                "NO OTHER ACTIONS ARE ALLOWED.\n\n"
                "CORRECT SYNTAX EXAMPLE:\n"
                "<report>\n"
                "contexts:\n"
                "  - id: \"context_name\"\n"
                "    content: \"Context content here\"\n"
                "comments: \"Summary of what was attempted and what went wrong\"\n"
                "</report>\n\n"
                "Instructions:\n"
                "1. Use ONLY the <report> action with proper YAML syntax\n"
                "2. Include any contexts you discovered before the errors\n"
                "3. In comments, explain what you were trying to do but you kept getting parsing errors so could not complete\n\n"
                "SUBMIT YOUR REPORT NOW WITH CORRECT SYNTAX."
            )
        elif reason_type == "no_actions":
            return (
                "\n\n⚠️ CRITICAL: MAXIMUM CONSECUTIVE NO-ACTION TURNS REACHED ⚠️\n"
                f"You have had {consecutive_errors} consecutive turns without attempting any actions.\n"
                "You are not making progress on the task.\n\n"
                "You MUST now submit a report using ONLY the <report> action.\n"
                "NO OTHER ACTIONS ARE ALLOWED.\n\n"
                "CORRECT SYNTAX EXAMPLE:\n"
                "<report>\n"
                "contexts:\n"
                "  - id: \"context_name\"\n"
                "    content: \"Context content here\"\n"
                "comments: \"Summary of what was attempted and what went wrong\"\n"
                "</report>\n\n"
                "Instructions:\n"
                "1. Use ONLY the <report> action with proper YAML syntax\n"
                "2. Include any contexts you discovered before stopping\n"
                "3. In comments, explain what you were trying to do and why you stopped taking actions\n\n"
                "SUBMIT YOUR REPORT NOW WITH CORRECT SYNTAX."
            )
        elif reason_type == "max_turns":
            return (
                "\n\n⚠️ CRITICAL: MAXIMUM TURNS REACHED ⚠️\n"
                "You have reached the maximum number of allowed turns.\n"
                "You MUST now submit a report using ONLY the <report> action.\n"
                "NO OTHER ACTIONS ARE ALLOWED.\n\n"
                "Instructions:\n"
                "1. Use ONLY the <report> action\n"
                "2. Include ALL contexts you have discovered so far\n"
                "3. In the comments section:\n"
                "   - Summarize what you have accomplished\n"
                "   - If the task is incomplete, explain what remains to be done\n"
                "   - Describe what you were about to do next and why\n\n"
                "SUBMIT YOUR REPORT NOW."
            )
        elif reason_type == "timeout":
            return (
                f"\n\n⚠️ CRITICAL: TIME LIMIT EXCEEDED ⚠️\n"
                f"You have exceeded the execution time limit ({self.max_execution_time_seconds:.1f} seconds).\n"
                f"Elapsed time: {elapsed_time:.1f} seconds\n\n"
                "You MUST now submit a report using ONLY the <report> action.\n"
                "NO OTHER ACTIONS ARE ALLOWED.\n\n"
                "Instructions:\n"
                "1. Use ONLY the <report> action\n"
                "2. Include ALL contexts you have discovered so far\n"
                "3. In the comments section:\n"
                "   - Summarize what you have accomplished\n"
                "   - If the task is incomplete, explain what remains to be done\n"
                "   - Describe what you were working on when time ran out\n\n"
                "SUBMIT YOUR REPORT NOW."
            )
        else:
            raise ValueError(f"Unknown reason type: {reason_type}")
    
    async def _force_report(self, reason_type: str, turn_num: int,
                     consecutive_errors: int = 0, elapsed_time: float = 0) -> SubagentReport:
        """Force the agent to submit a report for a given reason.

        Args:
            reason_type: Type of forcing reason ('parsing_errors', 'max_turns', or 'timeout')
            turn_num: Current turn number
            consecutive_errors: Number of consecutive errors (for parsing_errors)
            elapsed_time: Time elapsed in seconds (for timeout)
        """

        # Generate and append the force message
        force_message = self._generate_force_message(reason_type, consecutive_errors, elapsed_time)
        self._append_to_last_user_message(force_message)

        # Try to get report from agent
        try:
            llm_response = await self._get_llm_response(self.messages)
            self.messages.append({"role": "assistant", "content": llm_response})

            # Execute to extract the report
            result = await self.turn_exec.execute(llm_response)

            # Check for report action
            report = self._check_for_report(result.actions_executed)
            if report:
                self._set_report_metadata(report, turn_num + 1)
                return report
        except Exception as e:
            print(f"[AGENT-{self.agent_id}] [ERROR] Error while forcing report: {e}")

        # Fallback if report still not provided
        if reason_type == "parsing_errors":
            fallback_comment = f"Task incomplete - {consecutive_errors} consecutive parsing errors. Failed to provide proper report."
        elif reason_type == "no_actions":
            fallback_comment = f"Task incomplete - {consecutive_errors} consecutive turns with no actions attempted. Failed to provide proper report."
        elif reason_type == "timeout":
            fallback_comment = (
                f"Task incomplete - execution time limit exceeded ({elapsed_time:.1f}s / {self.max_execution_time_seconds:.1f}s). "
                f"Agent failed to provide proper report when requested."
            )
        else:  # max_turns
            fallback_comment = f"Task incomplete - reached maximum turns ({self.max_turns}) without proper completion. Agent failed to provide report when requested."

        return SubagentReport(
            contexts=[],
            comments=fallback_comment,
            meta=SubagentMeta(
                trajectory=self.messages.copy(),
                num_turns=turn_num + 1 if reason_type == "parsing_errors" else self.max_turns,
                total_input_tokens=self.total_input_tokens,
                total_output_tokens=self.total_output_tokens
            )
        )
    
    async def _force_report_for_parsing_errors(self, turn_num: int) -> SubagentReport:
        """Force the agent to submit a report due to consecutive parsing errors."""
        return await self._force_report("parsing_errors", turn_num, self.consecutive_parse_errors)

    async def _force_report_for_no_actions(self, turn_num: int) -> SubagentReport:
        """Force the agent to submit a report due to consecutive no-action turns."""
        return await self._force_report("no_actions", turn_num, self.consecutive_no_actions)

    async def _force_report_for_max_turns(self) -> SubagentReport:
        """Force the agent to submit a report when max turns is reached."""
        return await self._force_report("max_turns", self.max_turns)

    async def _force_report_for_timeout(self, turn_num: int, elapsed_time: float) -> SubagentReport:
        """Force the agent to submit a report when execution time limit is reached.

        Args:
            turn_num: Current turn number
            elapsed_time: Time elapsed in seconds
        """
        return await self._force_report("timeout", turn_num, elapsed_time=elapsed_time)
    
    async def _handle_parsing_errors(self, result, turn_num: int) -> Optional[SubagentReport]:
        """Handle parsing errors and no-action cases, returning a forced report if threshold is met."""
        # Check for no actions executed (either parsing error or no action attempt)
        if not result.actions_executed:
            # Distinguish between parsing errors and no-action attempts
            if result.has_parsing_error:
                self.consecutive_parse_errors += 1
                self.consecutive_no_actions = 0  # Reset no-action counter

                # Check if we've hit the consecutive parsing error threshold
                if self.consecutive_parse_errors >= self.max_consecutive_parse_errors:
                    # Add current error responses to messages before forcing
                    env_response = "\n".join(result.env_responses)
                    self.messages.append({"role": "user", "content": env_response})
                    return await self._force_report_for_parsing_errors(turn_num)
            else:
                # No actions were attempted (not a parsing error, just no actions)
                self.consecutive_no_actions += 1
                self.consecutive_parse_errors = 0  # Reset parsing error counter

                # Check if we've hit the consecutive no-action threshold
                if self.consecutive_no_actions >= self.max_consecutive_parse_errors:
                    # Add current responses to messages before forcing
                    env_response = "\n".join(result.env_responses)
                    self.messages.append({"role": "user", "content": env_response})
                    return await self._force_report_for_no_actions(turn_num)

            return None  # Continue with normal flow

        # Reset counters on successful action execution
        if result.actions_executed:
            self.consecutive_parse_errors = 0
            self.consecutive_no_actions = 0

        return None
    
    async def run(self) -> SubagentReport:
        """Execute the task and return the report."""
        # Start tracking execution time
        self.start_time = time.time()

        # Load system message asynchronously if not already loaded
        if self.system_message is None:
            self.system_message = self._load_system_message()

        # Get initial environment state
        env_info_retriever = EnvInfoRetriever(self.executor)
        env_context = await env_info_retriever.run_and_format(title="Initial Env State")

        # Build task prompt and append environment context
        task_prompt = self._build_task_prompt()
        initial_prompt_with_env = task_prompt + "\n\n" + env_context

        # Initialize message history with environment context included
        self.messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": initial_prompt_with_env}
        ]

        for turn_num in range(self.max_turns):
            # Check for timeout
            if self.max_execution_time_seconds is not None:
                elapsed_time = time.time() - self.start_time
                if elapsed_time >= self.max_execution_time_seconds:
                    return await self._force_report_for_timeout(turn_num, elapsed_time)
            
            try:
                # Get LLM response
                llm_response = await self._get_llm_response(self.messages)

                logger.debug(f"--- Subagent Turn {turn_num + 1} ---")
                logger.debug(f"LLM Response:\n{llm_response}")
                
                # Add assistant response to message history
                self.messages.append({"role": "assistant", "content": llm_response})
                
                # Execute actions
                result = await self.turn_exec.execute(llm_response)

                # Check for parsing errors and handle if threshold is met
                forced_report = await self._handle_parsing_errors(result, turn_num)
                if forced_report:
                    return forced_report

                # Add environment responses to message history
                env_response = result.to_user_msg_content()
                env_response = self._truncate_env_response(env_response)
                env_response += f"\n\nturns_used/max_turns: {turn_num + 1}/{self.max_turns}"
                if turn_num + 1 == self.max_turns:
                    env_response += " (FINAL TURN - YOU MUST SUBMIT <report> action, NO OTHER ACTIONS ALLOWED, if you have not completed the task, explain what you have done and what remains to be done (if anything) in the comments section)"


                # Log turn to session tracker if available
                if self.session_tracker:
                    # Get just the action names, not the full string representation
                    action_names = [type(action).__name__ for action in result.actions_executed]
                    await self.session_tracker.add_turn(
                        llm_output=llm_response,
                        env_response=env_response,
                        actions=action_names
                    )
                
                self.messages.append({"role": "user", "content": env_response})
                logger.debug(f"Environment Response:\n{env_response}")

                # Check for report action
                report = self._check_for_report(result.actions_executed)
                if report:
                    self.report = report
                    # Add metadata
                    self._set_report_metadata(report, turn_num + 1)
                    return report
                
            except ContextWindowExceededError:
                context_error_msg = (
                    f"⚠️ CONTEXT WINDOW EXCEEDED ⚠️\n\n"
                    f"The conversation has exceeded the model's context window limit at turn {turn_num + 1}.\n"
                    f"Task: {self.task.title}\n\n"
                    "Unable to continue processing or confirm task completion status.\n"
                    "Any work completed before this point cannot be verified or summarized.\n"
                    "The conversation history became too large for the model to process further.\n\n"
                    "Recommendations:\n"
                    "- Break down the task into smaller subtasks\n"
                    "- Use a model with a larger context window\n"
                    "- Reduce the verbosity of responses"
                )

                self.messages.append({"role": "user", "content": context_error_msg})

                report = SubagentReport(
                    contexts=[],  # No contexts can be reliably extracted
                    comments=context_error_msg,  # Use the detailed error message as comments
                    meta=SubagentMeta(
                        trajectory=self.messages.copy(),
                        num_turns=turn_num + 1,
                        total_input_tokens=self.total_input_tokens,
                        total_output_tokens=self.total_output_tokens
                    )
                )

                return report

            except Exception as e:
                # Add error to message history and continue
                self.messages.append({"role": "user", "content": f"Error occurred: {str(e)}. Please continue."})
        
        # Max turns reached - force the agent to create a report
        return await self._force_report_for_max_turns()