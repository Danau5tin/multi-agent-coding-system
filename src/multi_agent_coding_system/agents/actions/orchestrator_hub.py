"""Task Manager for coordinating between Orchestrator and subagents."""

import logging
from typing import Dict, List, Optional

from multi_agent_coding_system.agents.actions.entities.context import Context
from multi_agent_coding_system.agents.actions.entities.subagent_report import SubagentReport
from multi_agent_coding_system.agents.actions.entities.subagent_result import SubagentResult, VerboseSubagentResult
from multi_agent_coding_system.agents.actions.entities.task import ContextBootstrapItem, Task, TaskStatus
from multi_agent_coding_system.agents.actions.hierarchical_task_manager import HierarchicalTaskManager


logger = logging.getLogger(__name__)


class OrchestratorHub:
    """Central coordination hub for Orchestrator, allowing the agent to manage tasks and the context store."""
    
    def __init__(self, agent_id: str, task_manager: HierarchicalTaskManager):
        self.agent_id = agent_id  # The ID of the agent using this hub
        self.task_manager =  task_manager
        self.context_store: Dict[str, Context] = {}
        
    def create_task(
        self,
        agent_type: str,
        title: str,
        description: str,
        max_turns: int,
        context_refs: List[str],
        context_bootstrap: List[dict],
        parent_task_id: Optional[str] = None
    ) -> str:
        # Convert bootstrap dicts to objects
        bootstrap_items = [
            ContextBootstrapItem(path=item['path'], reason=item['reason'])
            for item in context_bootstrap
        ]
        
        # Use hierarchical task manager to create task
        if parent_task_id:
            # Create subtask
            task_id = self.task_manager.create_subtask(
                parent_id=parent_task_id,
                title=title,
                description=description,
                max_turns=max_turns,
                owner_id=self.agent_id,
                agent_type=agent_type,
                context_refs=context_refs,
                context_bootstrap=bootstrap_items
            )
        else:
            # Create root task
            task_id = self.task_manager.create_task(
                title=title,
                description=description,
                owner_id=self.agent_id,
                agent_type=agent_type,
                max_turns=max_turns,
                context_refs=context_refs,
                context_bootstrap=bootstrap_items
            )
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        return self.task_manager.get_task(task_id)
    
    def update_task_status(self, task_id: str, status: TaskStatus, error_message: Optional[str] = None) -> bool:
        """Update the status of a task.
        
        Returns:
            True if successful, False if task not found
        """
        try:
            return self.task_manager.update_status(
                task_id=task_id,
                status=status,
                owner_id=self.agent_id,
                error_message=error_message
            )
        except (ValueError, PermissionError) as e:
            logger.warning(f"Failed to update task {task_id}: {e}")
            return False
    
    def view_all_tasks(self) -> str:
        """Return formatted view of all tasks with their hierarchical structure."""
        return self.task_manager.format_tree_display()
    
    def add_context(
        self,
        context_id: str,
        content: str,
        reported_by: str,
        task_id: Optional[str] = None,
    ) -> bool:
        
        if context_id in self.context_store:
            logger.warning(f"Context {context_id} already exists in main store")
            return False
        
        context = Context(
            id=context_id,
            content=content,
            reported_by=reported_by,
            task_id=task_id
        )
        
        self.context_store[context_id] = context
        logger.info(f"Added context {context_id} to main store")
        return True
    
    def get_contexts_for_task(self, context_refs: List[str]) -> tuple[Dict[str, str], int, int]:
        """Get multiple contexts by their IDs or task IDs.

        If a ref is a task_id (format: 'task_XXX'), all contexts reported by that task
        will be included. Otherwise, treats ref as a direct context_id.

        Returns:
            Tuple of (contexts_dict, successful_refs_count, missing_refs_count)
            - contexts_dict: Dictionary mapping context_id to content
            - successful_refs_count: Number of context_refs that successfully resolved
            - missing_refs_count: Number of context_refs that didn't resolve to any contexts
        """
        contexts = {}
        successful_refs_count = 0
        missing_refs_count = 0

        for ref in context_refs:
            # Check if this is a task_id reference
            if ref.startswith(HierarchicalTaskManager.TASK_ID_PREFIX):
                # Fetch all contexts associated with this task
                ref = ref.removesuffix("_output")
                task_contexts = self._get_contexts_by_task_id(ref)
                if task_contexts:
                    contexts.update(task_contexts)
                    successful_refs_count += 1
                    logger.info(f"Loaded {len(task_contexts)} contexts from task {ref}")
                else:
                    missing_refs_count += 1
                    logger.warning(f"No contexts found for task {ref}")
            else:
                # Direct context reference
                context = self.context_store.get(ref)
                if context:
                    contexts[ref] = context.content
                    successful_refs_count += 1
                else:
                    missing_refs_count += 1
                    logger.warning(f"Context {ref} not found")

        return contexts, successful_refs_count, missing_refs_count

    def _get_contexts_by_task_id(self, task_id: str) -> Dict[str, str]:
        """Get all contexts reported by a specific task.

        Returns:
            Dictionary mapping context_id to content for all contexts from this task
        """
        task_contexts = {}
        for context_id, context in self.context_store.items():
            if context.task_id == task_id:
                task_contexts[context_id] = context.content

        return task_contexts
    
    def get_available_context_refs(self) -> List[str]:
        """Get list of all available context references (context IDs and task IDs).

        Returns:
            List of all available context_ids and task_ids that can be referenced
        """
        available_refs = []

        # Add all context IDs
        available_refs.extend(self.context_store.keys())

        # Add all task IDs that have associated contexts
        task_ids_with_contexts = set()
        for context in self.context_store.values():
            if context.task_id:
                task_ids_with_contexts.add(context.task_id)

        available_refs.extend(sorted(task_ids_with_contexts))

        return sorted(available_refs)

    def validate_context_refs(self, context_refs: List[str]) -> Optional[str]:
        """Validate context references and return error message if invalid.

        Args:
            context_refs: List of context references to validate

        Returns:
            Error message string if validation fails, None if all refs are valid
        """
        if not context_refs:
            return None

        _, _, missing_refs = self.get_contexts_for_task(context_refs)

        if missing_refs > 0:
            available_refs = self.get_available_context_refs()
            error_msg_lines = [
                "[ERROR] Invalid context references provided.",
                "",
                "Available context references:",
            ]

            if available_refs:
                for ref in available_refs:
                    error_msg_lines.append(f"  - {ref}")
                error_msg_lines.append("Please choose from the available context references and try again")
            else:
                error_msg_lines.append("  (none - context store is empty)")
                error_msg_lines.append("Please try again with no context references or after contexts have been added")
            
            error_msg_lines.append("The task(s) will not be created.")

            return "\n".join(error_msg_lines)

        return None

    def view_context_store(self) -> str:
        """Return formatted summary of all stored contexts."""
        if not self.context_store:
            return "Context store is empty."

        lines = ["Context Store:"]
        for context_id, context in self.context_store.items():
            # Get first line of content for summary
            lines.append(f"  Id: [{context_id}]")
            lines.append(f"     Content: {context.content}")
            lines.append(f"     Reported by: {context.reported_by}")

            if context.task_id:
                lines.append(f"    Task: {context.task_id}")

        return "\n".join(lines)
    
    def process_subagent_result(
        self,
        task_id: str,
        report: SubagentReport,
        verbose: bool = False,
    ) -> SubagentResult:
        """Process subagent output and extract contexts.

        Args:
            task_id: The task that was executed
            report: Report from subagent containing contexts and comments
            verbose: If True, return VerboseSubagentResult with full context content

        Returns:
            Processed result for Orchestrator containing context_ids and comments
            (or VerboseSubagentResult if verbose=True)
        """
        # Track all context IDs (both new and promoted)
        stored_context_ids = []
        contexts_dict = {}  # For verbose mode: maps context_id -> content
        duplicate_count = 0  # Track how many contexts were duplicates

        for ctx in report.contexts:
            if not ctx.id or not ctx.content:
                continue

            success = self.add_context(
                context_id=ctx.id,
                content=ctx.content,
                reported_by=task_id,
                task_id=task_id,
            )

            if success:
                stored_context_ids.append(ctx.id)
                if verbose:
                    contexts_dict[ctx.id] = ctx.content
            else:
                duplicate_count += 1
                logger.warning(f"Context {ctx.id} already exists in main store")

        # Create result object - verbose or standard depending on flag
        if verbose:
            result = VerboseSubagentResult(
                task_id=task_id,
                context_ids_stored=stored_context_ids,
                comments=report.comments,
                contexts=contexts_dict,
                duplicate_contexts_count=duplicate_count
            )
        else:
            result = SubagentResult(
                task_id=task_id,
                context_ids_stored=stored_context_ids,
                comments=report.comments,
                duplicate_contexts_count=duplicate_count
            )

        # Update task with result
        task = self.get_task(task_id)
        if task:
            task.result = result
            self.update_task_status(task_id, TaskStatus.COMPLETED)

        return result
