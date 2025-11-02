"""Stateless executor for single-turn agent execution with state management."""

import logging
from multi_agent_coding_system.agents.actions.parsing.action_handler import ActionHandler
from multi_agent_coding_system.agents.actions.parsing.parser import SimpleActionParser
from multi_agent_coding_system.agents.actions.entities.actions import (
    FinishAction,
)
from multi_agent_coding_system.agents.env_interaction.entities.execution_result import ExecutionResult

logger = logging.getLogger(__name__)


class TurnExecutor:
    """Executes a single turn of agent interaction"""

    def __init__(
        self,
        action_parser: SimpleActionParser,
        action_handler: ActionHandler,
    ):
        self.action_parser = action_parser
        self.action_handler = action_handler

    async def execute(self, llm_output: str) -> ExecutionResult:
        """Execute actions from LLM output and return result.

        Args:
            llm_output: Raw output from the LLM

        Returns:
            ExecutionResult containing executed actions and responses
        """
        # Parse actions from LLM output
        actions, parsing_errors, found_action_attempt = (
            self.action_parser.parse_response(llm_output)
        )

        if not found_action_attempt:
            return ExecutionResult(
                actions_executed=[],
                env_responses=[
                    "No actions were attempted by you in the last turn. YOU MUST RESPOND WITH ONE OF THE ACTIONS EXPLAINED TO YOU IN THE SYSTEM MESSAGE. Actions follow the format <action_name>\n{action content}\n</action_name>.\n\nNow you must respond with the next best action."
                ],
                has_error=True,
                done=True,
                has_parsing_error=False,
            )

        # Track execution
        actions_executed = []
        env_responses = []
        has_error = False
        finish_message = None
        done = False

        # Handle parsing errors
        if parsing_errors:
            has_error = True
            # Include parsing errors in env responses
            for error in parsing_errors:
                env_responses.append(f"[PARSE ERROR] {error}")

            # If no valid actions were parsed, return early
            if not actions:
                return ExecutionResult(
                    actions_executed=[],
                    env_responses=env_responses,
                    has_error=True,
                    done=False,
                    has_parsing_error=True,
                )

        # Execute each action
        for action in actions:
            try:
                # Execute the action
                output, is_error = await self.action_handler.handle_action(action)
                actions_executed.append(action)

                if is_error:
                    has_error = True

                env_responses.append(output)

                # Check for finish
                if isinstance(action, FinishAction):
                    finish_message = action.message
                    done = True
                    break

            except Exception as e:
                env_responses.append(f"[ERROR] Action execution failed: {str(e)}")
                has_error = True

        # Collect any subagent trajectories from this execution
        subagent_trajectories = (
            self.action_handler.get_and_clear_subagent_trajectories()
        )

        # Collect duplicate contexts count from this turn
        duplicate_contexts_count = (
            self.action_handler.get_and_clear_duplicate_contexts_count()
        )

        # Collect context reference resolution stats from this turn
        successful_context_refs, missing_context_refs = (
            self.action_handler.get_and_clear_context_ref_stats()
        )

        return ExecutionResult(
            actions_executed=actions_executed,
            env_responses=env_responses,
            has_error=has_error,
            finish_message=finish_message,
            done=done,
            subagent_trajectories=subagent_trajectories
            if subagent_trajectories
            else None,
            has_parsing_error=bool(parsing_errors),
            duplicate_contexts_count=duplicate_contexts_count,
            successful_context_refs=successful_context_refs,
            missing_context_refs=missing_context_refs,
        )
