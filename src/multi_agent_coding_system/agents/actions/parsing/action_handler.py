"""Action handler for executing parsed actions in the RLLM environment."""

import logging
import time
from typing import Dict, Callable, Tuple, Optional, Any
import uuid

from multi_agent_coding_system.agents.utils.time_utils import format_elapsed_time_with_prefix
from multi_agent_coding_system.agents.actions.entities.task import Task
from multi_agent_coding_system.agents.env_interaction.command_executor import CommandExecutor
from multi_agent_coding_system.agents.actions.orchestrator_hub import OrchestratorHub
from multi_agent_coding_system.agents.actions.entities.subagent_result import SubagentResult, VerboseSubagentResult
from multi_agent_coding_system.agents.actions.entities.actions import (
    Action,
    BatchTodoAction,
    AddNoteAction,
    ViewAllNotesAction,
    ReadAction,
    WriteAction,
    EditAction,
    MultiEditAction,
    GrepAction,
    GlobAction,
    FileMetadataAction,
    WriteTempScriptAction,
    BashAction,
    FinishAction,
    TaskCreateAction,
    AddContextAction,
    LaunchSubagentAction,
    ReportAction,
)
from multi_agent_coding_system.agents.actions.state_managers import TodoManager, ScratchpadManager
from multi_agent_coding_system.agents.actions.file_manager import FileManager
from multi_agent_coding_system.agents.actions.search_manager import SearchManager

logger = logging.getLogger(__name__)

NUM_SECS_REQ_TO_SHOW_BASH_ELAPSED = 5

def format_tool_output(tool_name: str, content: str) -> str:
    """Format tool output in XML format.
    
    Args:
        tool_name: Name of the tool (e.g., 'todo', 'file', 'search')
        content: The raw content to wrap
        
    Returns:
        XML-formatted output string
    """
    tag_name = f"{tool_name}_output"
    return f"<{tag_name}>\n{content}\n</{tag_name}>"


class ActionHandler:
    """Handles execution of different action types."""
    
    @staticmethod
    def truncate_content(content: str, max_length: int = 15) -> str:
        """Truncate content for display to reduce tokens."""
        return content[:max_length] + "..." if len(content) > max_length else content
    
    def __init__(
        self,
        executor: CommandExecutor,
        todo_manager: Optional[TodoManager] = None,
        scratchpad_manager: Optional[ScratchpadManager] = None,
        orchestrator_hub: Optional[OrchestratorHub] = None,
        logging_dir: Optional[Any] = None,
        depth: int = 0,
        parent_agent_id: Optional[str] = None,
        session_logger: Optional[Any] = None,
        max_rollout_time: Optional[float] = None,
        rollout_start_time: Optional[float] = None,
        verbose_outputs: bool = False,
    ):
        self.executor = executor

        self.todo_manager = todo_manager or TodoManager()
        self.scratchpad_manager = scratchpad_manager or ScratchpadManager()
        self.file_manager = FileManager(executor)
        self.search_manager = SearchManager(executor)
        self.parent_agent_id = parent_agent_id
        self.orchestrator_hub = orchestrator_hub

        # Store LLM configuration for subagents
        self.logging_dir = logging_dir
        self.depth = depth  # Current agent depth (0=orchestrator, 1=subagent, 2=sub-subagent)
        self.session_logger = session_logger  # Session logger for tracking execution

        # Store rollout timing information for subagent time limits
        self.max_rollout_time = max_rollout_time
        self.rollout_start_time = rollout_start_time

        # Verbose output mode - if True, include full context content in subagent results
        self.verbose_outputs = verbose_outputs

        # Track subagent trajectories for current execution
        self.subagent_trajectories: Dict[str, Dict[str, Any]] = {}

        # Track duplicate contexts from all subagents in current turn
        self.turn_duplicate_contexts_count: int = 0

        # Track context reference resolution stats for current turn
        self.turn_successful_context_refs: int = 0
        self.turn_missing_context_refs: int = 0

        # Map action types to handler methods
        self._handlers: Dict[type, Callable] = {
            BatchTodoAction: self._handle_batch_todo,
            AddNoteAction: self._handle_add_note,
            ViewAllNotesAction: self._handle_view_all_notes,
            ReadAction: self._handle_read_file,
            WriteAction: self._handle_write_file,
            EditAction: self._handle_edit_file,
            MultiEditAction: self._handle_multi_edit_file,
            GrepAction: self._handle_grep,
            GlobAction: self._handle_glob,
            FileMetadataAction: self._handle_file_metadata,
            WriteTempScriptAction: self._handle_write_temp_script,
            BashAction: self._handle_bash,
            FinishAction: self._handle_finish,
            TaskCreateAction: self._handle_task_create,
            AddContextAction: self._handle_add_context,
            LaunchSubagentAction: self._handle_launch_subagent,
            ReportAction: self._handle_report,
        }
    
    async def handle_action(self, action: Action) -> Tuple[str, bool]:
        """Handle an action and return (response, is_error)."""
        handler = self._handlers.get(type(action))
        if handler:
            return await handler(action)
        content = f"[ERROR] Unknown action type: {type(action).__name__}"
        return format_tool_output("unknown", content), True

    def _check_sufficient_time_for_subagent(self, min_seconds: float = 30.0) -> Tuple[bool, float]:
        """Check if there's enough time remaining to launch a subagent.

        Args:
            min_seconds: Minimum seconds required

        Returns:
            Tuple of (has_sufficient_time, remaining_time)
        """
        if self.max_rollout_time is None or self.rollout_start_time is None:
            return True, float('inf')  # No time limit set

        elapsed = time.time() - self.rollout_start_time
        remaining_time = self.max_rollout_time - elapsed

        return remaining_time >= min_seconds, remaining_time
    
    
    async def _handle_batch_todo(self, action: BatchTodoAction) -> Tuple[str, bool]:
        """Handle batch todo operations."""
        results = []
        has_error = False
        
        for op in action.operations:
            if op.action == "add":
                task_id = self.todo_manager.add_task(op.content)
                truncated_content = self.truncate_content(op.content)
                results.append(f"Added todo [{task_id}]: {truncated_content}")
            
            elif op.action == "complete":
                task = self.todo_manager.get_task(op.task_id)
                if not task:
                    results.append(f"[ERROR] Task {op.task_id} not found")
                    has_error = True
                elif task["status"] == "completed":
                    results.append(f"Task {op.task_id} is already completed")
                else:
                    self.todo_manager.complete_task(op.task_id)
                    truncated_content = self.truncate_content(task['content'])
                    results.append(f"Completed task [{op.task_id}]: {truncated_content}")
            
            elif op.action == "delete":
                task = self.todo_manager.get_task(op.task_id)
                if not task:
                    results.append(f"[ERROR] Task {op.task_id} not found")
                    has_error = True
                else:
                    self.todo_manager.delete_task(op.task_id)
                    truncated_content = self.truncate_content(task['content'])
                    results.append(f"Deleted task [{op.task_id}]: {truncated_content}")
        
        # Join results
        response = "\n".join(results)
        
        # Add todo list if requested
        if action.view_all:
            response += f"\n\n{self.todo_manager.view_all()}"
        
        return format_tool_output("todo", response), has_error
    
    async def _handle_add_note(self, action: AddNoteAction) -> Tuple[str, bool]:
        """Handle adding a note to scratchpad."""
        if not action.content:
            return format_tool_output("scratchpad", "[ERROR] Cannot add empty note"), True
        
        note_idx = self.scratchpad_manager.add_note(action.content)
        response = f"Added note {note_idx + 1} to scratchpad"
        return format_tool_output("scratchpad", response), False
    
    async def _handle_view_all_notes(self, action: ViewAllNotesAction) -> Tuple[str, bool]:
        """Handle viewing all notes."""
        return format_tool_output("scratchpad", self.scratchpad_manager.view_all()), False
    
    async def _handle_read_file(self, action: ReadAction) -> Tuple[str, bool]:
        """Handle reading a file."""
        content, is_error = await self.file_manager.read_file(
            action.file_path, action.offset, action.limit
        )
        return format_tool_output("file", content), is_error
    
    async def _handle_write_file(self, action: WriteAction) -> Tuple[str, bool]:
        """Handle writing a file."""
        content, is_error = await self.file_manager.write_file(
            action.file_path, action.content
        )
        return format_tool_output("file", content), is_error
    
    async def _handle_edit_file(self, action: EditAction) -> Tuple[str, bool]:
        """Handle editing a file."""
        content, is_error = await self.file_manager.edit_file(
            action.file_path, action.old_string, action.new_string, action.replace_all
        )
        return format_tool_output("file", content), is_error
    
    async def _handle_multi_edit_file(self, action: MultiEditAction) -> Tuple[str, bool]:
        """Handle multiple edits to a file."""
        edits = [(e.old_string, e.new_string, e.replace_all) for e in action.edits]
        content, is_error = await self.file_manager.multi_edit_file(
            action.file_path, edits
        )
        return format_tool_output("file", content), is_error
    
    async def _handle_grep(self, action: GrepAction) -> Tuple[str, bool]:
        """Handle grep search."""
        content, is_error = await self.search_manager.grep(
            action.pattern, action.path, action.include
        )
        return format_tool_output("search", content), is_error
    
    async def _handle_glob(self, action: GlobAction) -> Tuple[str, bool]:
        """Handle glob search."""
        content, is_error = await self.search_manager.glob(
            action.pattern, action.path
        )
        return format_tool_output("search", content), is_error
    
    async def _handle_file_metadata(self, action: FileMetadataAction) -> Tuple[str, bool]:
        """Handle file metadata request."""
        content, is_error = await self.file_manager.get_metadata(action.file_paths)
        return format_tool_output("file", content), is_error
    
    async def _handle_write_temp_script(self, action: WriteTempScriptAction) -> Tuple[str, bool]:
        """Handle writing a temporary script file.

        This uses the same underlying file write functionality but is specifically
        intended for temporary scripts used during exploration/testing.
        """
        # Use the existing file write functionality
        content, is_error = await self.file_manager.write_file(
            action.file_path, action.content
        )
        return format_tool_output("file", content), is_error
    
    async def _handle_bash(self, action: BashAction) -> Tuple[str, bool]:
        """Handle bash command execution."""
        try:
            start_time = time.time()
            if action.block:
                # Calculate effective timeout - cap to remaining rollout time
                effective_timeout = action.timeout_secs
                if self.max_rollout_time is not None and self.rollout_start_time is not None:
                    elapsed = time.time() - self.rollout_start_time
                    remaining_time = self.max_rollout_time - elapsed

                    # Cap timeout to remaining time (leave 5s buffer for cleanup)
                    max_allowed_timeout = int(max(remaining_time - 5, 5))  # Minimum 5s, convert to int

                    if effective_timeout is None or effective_timeout > max_allowed_timeout:
                        effective_timeout = max_allowed_timeout
                        logger.info(f"Capping bash timeout from {action.timeout_secs}s to {effective_timeout}s (remaining rollout time: {remaining_time:.1f}s)")

                output, exit_code = await self.executor.execute(
                    action.cmd,
                    timeout=effective_timeout
                )
            else:
                # Non-blocking execution
                await self.executor.execute_background(action.cmd)
                output = "Command started in background"
                exit_code = 0

            elapsed_time = time.time() - start_time
            
            if elapsed_time < NUM_SECS_REQ_TO_SHOW_BASH_ELAPSED:
                # If command was very quick, don't show elapsed time to save tokens
                return format_tool_output("bash", output), exit_code != 0
            
            elapsed_str = format_elapsed_time_with_prefix(start_time, prefix="\n\n## Command took (mm:ss): ")
            output += elapsed_str
            is_error = exit_code != 0
            return format_tool_output("bash", output), is_error

        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            return format_tool_output("bash", error_msg), True
    
    async def _handle_finish(self, action: FinishAction) -> Tuple[str, bool]:
        """Handle finish action."""
        response = f"Task marked as complete: {action.message}"
        return format_tool_output("finish", response), False
    
    async def _handle_task_create(self, action: TaskCreateAction) -> Tuple[str, bool]:
        """Handle task creation."""
        if not self.orchestrator_hub:
            raise ValueError("OrchestratorHub is required to create tasks")
        try:
            task_id = self.orchestrator_hub.create_task(
                agent_type=action.agent_type,
                title=action.title,
                description=action.description,
                context_refs=action.context_refs,
                max_turns=action.max_turns,
                context_bootstrap=action.context_bootstrap
            )
            
            response = f"Created task {task_id}: {action.title}"
            
            # Auto-launch if requested
            if action.auto_launch:
                launch_action = LaunchSubagentAction(task_id=task_id)
                launch_response, launch_error = await self._handle_launch_subagent(launch_action)
                response += f"\n{launch_response}"
                return format_tool_output("task", response), launch_error
            
            return format_tool_output("task", response), False
            
        except Exception as e:
            error_msg = f"[ERROR] Failed to create task: {str(e)}"
            return format_tool_output("task", error_msg), True
    
    async def _handle_add_context(self, action: AddContextAction) -> Tuple[str, bool]:
        """Handle adding context to store."""
        if not self.orchestrator_hub:
            raise ValueError("OrchestratorHub is required to add context")
        try:
            success = self.orchestrator_hub.add_context(
                context_id=action.id,
                content=action.content,
                reported_by=action.reported_by,
                task_id=action.task_id
            )
            
            if success:
                response = f"Added context '{action.id}' to store"
            else:
                response = f"[WARNING] Context '{action.id}' already exists in store"
                
            return format_tool_output("context", response), not success
            
        except Exception as e:
            error_msg = f"[ERROR] Failed to add context: {str(e)}"
            return format_tool_output("context", error_msg), True
    
    async def _run_single_subagent(self, task_id: str, task: Task) -> SubagentResult:
        """Core logic for running a single subagent. Shared by both single and parallel launch.

        Args:
            task_id: The task ID
            task: The task object
            store_context: Whether to store contexts in the global store
        """
        from multi_agent_coding_system.agents.subagent import Subagent, SubagentTask
        if not self.orchestrator_hub:
            raise ValueError("OrchestratorHub is required to launch subagents")

        try:
            # Resolve context references and track stats
            context_store_ctxts, successful_refs, missing_refs = self.orchestrator_hub.get_contexts_for_task(task.context_refs)

            # Track context reference resolution for this turn
            self.turn_successful_context_refs += successful_refs
            self.turn_missing_context_refs += missing_refs

            bootstrap_ctxts = []

            if task.context_bootstrap:
                for item in task.context_bootstrap:
                    path = item.path
                    reason = item.reason
                    is_dir = path.endswith("/")
                    if is_dir:
                        ls_result, _ = await self.search_manager.ls(path, ignore=[])
                        bootstrap_ctxts.append({"path": path, "content": ls_result, "reason": reason})
                    else:
                        file_result, _ = await self.file_manager.read_file(path, offset=0, limit=1000)
                        bootstrap_ctxts.append({"path": path, "content": file_result, "reason": reason})
            
            subagent_task = SubagentTask(
                agent_type=task.agent_type,
                title=task.title,
                description=task.description,
                max_turns=task.max_turns,
                ctx_store_ctxts=context_store_ctxts,
                bootstrap_ctxts=bootstrap_ctxts
            )
            
            # Get or create consistent subagent ID for this task
            subagent_id = f"{self.parent_agent_id}->{str(uuid.uuid4())[:8]}"

            # Create subagent session tracker if we have a session logger
            subagent_session_tracker = None
            if self.session_logger:
                from multi_agent_coding_system.misc.session_logger import SubagentSessionTracker
                subagent_session_tracker = SubagentSessionTracker(
                    parent_logger=self.session_logger,
                    agent_id=subagent_id,
                    agent_type=task.agent_type,
                    task_title=task.title,
                    task_description=task.description,
                    max_turns=task.max_turns
                )

            # Calculate remaining time budget for subagent
            max_execution_time_seconds = None
            if self.max_rollout_time is not None and self.rollout_start_time is not None:
                elapsed = time.time() - self.rollout_start_time
                remaining_time = self.max_rollout_time - elapsed
                # Only set if there's meaningful time remaining (at least 5 seconds)
                if remaining_time > 5:
                    max_execution_time_seconds = remaining_time

            subagent = Subagent(
                agent_id=subagent_id,
                task=subagent_task,
                executor=self.executor,
                orchestrator_hub=self.orchestrator_hub,  # Pass down the shared orchestrator hub
                # Don't pass model, api_key, or api_base to allow ORCA_SUBAGENT_* env vars to take effect
                logging_dir=self.logging_dir,
                task_id=task_id,
                depth=self.depth + 1,  # Pass incremented depth,
                session_tracker=subagent_session_tracker,  # Pass the session tracker
                max_execution_time_seconds=max_execution_time_seconds,  # Pass time limit
            )

            report = await subagent.run()
            
            # Store trajectory and token counts
            if report.meta:
                self.subagent_trajectories[task_id] = {
                    'agent_type': task.agent_type,
                    'title': task.title,
                    'trajectory': report.meta.trajectory if report.meta.trajectory else None,
                    'total_input_tokens': report.meta.total_input_tokens,
                    'total_output_tokens': report.meta.total_output_tokens
                }

            # Finish the subagent session if we have a tracker
            if subagent_session_tracker:
                await subagent_session_tracker.finish(
                    report=report.__dict__ if report else None,
                    total_input_tokens=report.meta.total_input_tokens if report.meta else 0,
                    total_output_tokens=report.meta.total_output_tokens if report.meta else 0
                )
            
            result = self.orchestrator_hub.process_subagent_result(task_id, report, verbose=self.verbose_outputs)

            # Track duplicate contexts for this turn
            self.turn_duplicate_contexts_count += result.duplicate_contexts_count

            return result
            
        except Exception as e:
            return SubagentResult(
                task_id=task_id,
                error=str(e),
                context_ids_stored=[],
                comments=""
            )

    def _format_subagent_result(self, result: SubagentResult,
                                 task_title: str = None) -> Tuple[str, bool]:
        """Format a single subagent result into a response string.

        Args:
            result: The SubagentResult from the subagent
            task_title: Optional task title for richer formatting

        Returns:
            Tuple of (formatted_string, has_error)
        """
        if result.has_error:
            error_msg = f"[ERROR] Subagent failed: {result.error}"
            return error_msg, True

        # Format response
        response_lines = [
            f"Subagent completed task {result.task_id}" + (f" ({task_title})" if task_title else ""),
        ]

        # If verbose mode and we have a VerboseSubagentResult, include full context content
        if self.verbose_outputs and isinstance(result, VerboseSubagentResult):
            if result.contexts:
                response_lines.append(f"\nContexts stored ({len(result.contexts)}):")
                for ctx_id, ctx_content in result.contexts.items():
                    response_lines.append(f"\n  [{ctx_id}]:")
                    response_lines.append(f"  {ctx_content}")
            else:
                response_lines.append("Contexts stored: (none)")
        else:
            # Standard mode - just show context IDs
            response_lines.append(f"Contexts stored: {', '.join(result.context_ids_stored)}")

        if result.comments:
            response_lines.append(f"Comments: {result.comments}")

        return "\n".join(response_lines), False
    
    async def _handle_launch_subagent(self, action: LaunchSubagentAction) -> Tuple[str, bool]:
        """Handle launching a subagent for a task."""
        if not self.orchestrator_hub:
            raise ValueError("OrchestratorHub is required to launch subagents")

        # Check if there's enough time remaining to launch a subagent
        has_time, remaining_time = self._check_sufficient_time_for_subagent(min_seconds=30.0)
        if not has_time:
            error_msg = (
                f"[ERROR] Insufficient time to launch subagent. "
                f"Remaining time: {remaining_time:.1f}s (minimum required: 30s)"
            )
            return format_tool_output("subagent", error_msg), True

        task = self.orchestrator_hub.get_task(action.task_id)
        if not task:
            error_msg = f"[ERROR] Task {action.task_id} not found"
            return format_tool_output("subagent", error_msg), True

        # Validate context references before launching
        validation_error = self.orchestrator_hub.validate_context_refs(task.context_refs)
        if validation_error:
            return format_tool_output("subagent", validation_error), True

        start_time = time.time()

        result = await self._run_single_subagent(action.task_id, task)
        
        elapsed_secs = int(time.time() - start_time)
        # Format the result using common formatter
        response, has_error = self._format_subagent_result(result, task.title)
        response += f"\nTime taken by subagent: {elapsed_secs} seconds"
        
        return format_tool_output("subagent", response), has_error
    
    async def _handle_report(self, action: ReportAction) -> Tuple[str, bool]:
        return format_tool_output("report", "Report submission successful"), False
    
    def get_and_clear_subagent_trajectories(self) -> Dict[str, Dict[str, Any]]:
        """Get collected subagent trajectories and clear the internal store."""
        trajectories = self.subagent_trajectories.copy()
        self.subagent_trajectories.clear()
        return trajectories

    def get_and_clear_duplicate_contexts_count(self) -> int:
        """Get the count of duplicate contexts from this turn and reset the counter."""
        count = self.turn_duplicate_contexts_count
        self.turn_duplicate_contexts_count = 0
        return count

    def get_and_clear_context_ref_stats(self) -> tuple[int, int]:
        """Get context reference resolution stats from this turn and reset counters.

        Returns:
            Tuple of (successful_refs_count, missing_refs_count)
        """
        successful = self.turn_successful_context_refs
        missing = self.turn_missing_context_refs
        self.turn_successful_context_refs = 0
        self.turn_missing_context_refs = 0
        return successful, missing
