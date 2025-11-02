"""Hierarchical task management implementation for multi-agent systems."""

import logging
from typing import Dict, List, Optional
from threading import Lock
from multi_agent_coding_system.agents.actions.entities.task import Task, TaskStatus, ContextBootstrapItem
from multi_agent_coding_system.agents.actions.task_manager_base import TaskManagerABC

logger = logging.getLogger(__name__)


class HierarchicalTaskManager(TaskManagerABC):
    """Implementation of hierarchical task management with ownership and depth control.

    Features:
    - Parent-child task relationships
    - Ownership-based access control (agents can only modify tasks they own)
    - Depth limiting (max 2 levels deep)
    - Thread-safe operations for parallel agents
    - Full read access for all agents
    """

    TASK_ID_PREFIX = "task_"
    MAX_DEPTH = 2  # Orchestrator -> Subagent -> Sub-subagent
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.task_counter = 0
        self._lock = Lock()  # Thread safety for parallel agents
    
    def create_task(
        self, 
        title: str, 
        description: str, 
        owner_id: str,
        max_turns: int,
        agent_type: str = 'explorer',
        context_refs: List[str] = None,
        context_bootstrap: List[dict] = None,
        **kwargs
    ) -> str:
        """Create a new root task."""
        with self._lock:
            self.task_counter += 1
            task_id = f"{self.TASK_ID_PREFIX}{self.task_counter:03d}"
            
            # Convert dict items to ContextBootstrapItem objects
            bootstrap_items = []
            if context_bootstrap:
                for item in context_bootstrap:
                    if isinstance(item, dict):
                        bootstrap_items.append(ContextBootstrapItem(
                            path=item.get('path', ''),
                            reason=item.get('reason', '')
                        ))
                    elif isinstance(item, ContextBootstrapItem):
                        bootstrap_items.append(item)
            
            task = Task(
                task_id=task_id,
                agent_type=agent_type,
                title=title,
                description=description,
                max_turns=max_turns,
                context_refs=context_refs or [],
                context_bootstrap=bootstrap_items,
                owner_id=owner_id,
                depth=0,  # Root tasks start at depth 0
                parent_id=None
            )
            
            self.tasks[task_id] = task
            return task_id
    
    def create_subtask(
        self, 
        parent_id: str,
        title: str, 
        description: str, 
        max_turns: int,
        owner_id: str,
        agent_type: str = 'explorer',
        context_refs: List[str] = None,
        context_bootstrap: List[dict] = None,
        **kwargs
    ) -> str:
        """Create a subtask under an existing parent task."""
        with self._lock:
            # Validate parent exists
            parent = self.tasks.get(parent_id)
            if not parent:
                raise ValueError(f"Parent task {parent_id} does not exist")
            
            # Check depth limit
            if parent.depth >= self.MAX_DEPTH:
                raise ValueError(f"Maximum depth ({self.MAX_DEPTH}) exceeded. Cannot create subtask under {parent_id}")
            
            # Create subtask
            self.task_counter += 1
            task_id = f"{self.TASK_ID_PREFIX}{self.task_counter:03d}"
            
            # Convert dict items to ContextBootstrapItem objects
            bootstrap_items = []
            if context_bootstrap:
                for item in context_bootstrap:
                    if isinstance(item, dict):
                        bootstrap_items.append(ContextBootstrapItem(
                            path=item.get('path', ''),
                            reason=item.get('reason', '')
                        ))
                    elif isinstance(item, ContextBootstrapItem):
                        bootstrap_items.append(item)
            
            task = Task(
                task_id=task_id,
                agent_type=agent_type, # type: ignore
                title=title,
                description=description,
                max_turns=max_turns,
                context_refs=context_refs or [],
                context_bootstrap=bootstrap_items,
                owner_id=owner_id,
                depth=parent.depth + 1,
                parent_id=parent_id
            )
            
            # Update parent's child list
            parent.child_ids.append(task_id)
            
            self.tasks[task_id] = task
            logger.info(f"Created subtask {task_id} under {parent_id}: {title} (owner: {owner_id}, depth: {task.depth})")
            return task_id
    
    def update_status(
        self, 
        task_id: str, 
        status: TaskStatus, 
        owner_id: str, 
        error_message: Optional[str] = None
    ) -> bool:
        """Update the status of a task (only if owned by the requester)."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} does not exist")
            
            # Check ownership
            if task.owner_id != owner_id:
                raise PermissionError(f"Agent {owner_id} cannot modify task {task_id} owned by {task.owner_id}")
            
            # Update status
            task.status = status
            if error_message:
                task.error_message = error_message
            
            if status == TaskStatus.COMPLETED:
                from datetime import datetime
                task.completed_at = datetime.now().isoformat()
            
            logger.info(f"Updated task {task_id} status to {status.value} (by owner: {owner_id})")
            return True
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a single task by ID."""
        return self.tasks.get(task_id)
    
    def get_tree(self, root_id: Optional[str] = None) -> Dict:
        """Get hierarchical tree representation of tasks."""
        def build_tree_node(task: Task) -> Dict:
            """Recursively build tree node for a task and its children."""
            node = {
                'task_id': task.task_id,
                'title': task.title,
                'status': task.status.value,
                'owner_id': task.owner_id,
                'depth': task.depth,
                'error_message': task.error_message,
                'children': []
            }
            
            # Add children recursively
            for child_id in task.child_ids:
                child_task = self.tasks.get(child_id)
                if child_task:
                    node['children'].append(build_tree_node(child_task))
            
            return node
        
        if root_id:
            # Build tree from specific root
            root_task = self.tasks.get(root_id)
            if not root_task:
                return {}
            return build_tree_node(root_task)
        else:
            # Build all trees (find all root tasks)
            root_tasks = [t for t in self.tasks.values() if t.parent_id is None]
            return {
                'trees': [build_tree_node(root) for root in root_tasks]
            }
    
    def get_children(self, parent_id: str) -> List[Task]:
        """Get all direct children of a task."""
        parent = self.tasks.get(parent_id)
        if not parent:
            return []
        
        children = []
        for child_id in parent.child_ids:
            child = self.tasks.get(child_id)
            if child:
                children.append(child)
        
        return children
    
    def get_owned_tasks(self, owner_id: str) -> List[Task]:
        """Get all tasks owned by a specific agent."""
        return [task for task in self.tasks.values() if task.owner_id == owner_id]
    
    def can_modify(self, task_id: str, agent_id: str) -> bool:
        """Check if an agent has permission to modify a task."""
        task = self.tasks.get(task_id)
        if not task:
            return False
        return task.owner_id == agent_id
    
    def get_all_tasks(self) -> List[Task]:
        """Get all tasks in the system."""
        return list(self.tasks.values())
    
    def get_aggregated_status(self, task_id: str) -> TaskStatus:
        """Get aggregated status considering all descendants.
        
        Rules:
        - If task is a leaf (no children), return its own status
        - If any child is in_progress/created, parent is in_progress
        - If all children are completed, parent is completed
        - If any child failed, parent is completed (with error tracked separately)
        """
        task = self.tasks.get(task_id)
        if not task:
            return TaskStatus.CREATED
        
        # Leaf task - return its own status
        if not task.child_ids:
            return task.status
        
        # Get all child statuses recursively
        child_statuses = []
        for child_id in task.child_ids:
            child_status = self.get_aggregated_status(child_id)
            child_statuses.append(child_status)
        
        # Apply aggregation rules
        if any(s in [TaskStatus.CREATED, TaskStatus.FAILED] for s in child_statuses):
            # Any child still pending or in progress
            return TaskStatus.CREATED
        elif all(s == TaskStatus.COMPLETED for s in child_statuses):
            # All children completed
            return TaskStatus.COMPLETED
        else:
            # Mixed states - consider as in progress
            return TaskStatus.CREATED
    
    def format_tree_display(self, root_id: Optional[str] = None, indent: int = 0) -> str:
        """Format task tree for display."""
        lines = []
        
        def format_task(task: Task, level: int):
            """Format a single task with indentation."""
            indent_str = "  " * level
            status_symbol = {
                TaskStatus.CREATED: "○",
                TaskStatus.COMPLETED: "●",
                TaskStatus.FAILED: "✗"
            }.get(task.status, "?")
            
            # Get aggregated status if has children
            if task.child_ids:
                agg_status = self.get_aggregated_status(task.task_id)
                if agg_status != task.status:
                    status_symbol += f"→{agg_status.value[0].upper()}"
            
            lines.append(f"{indent_str}{status_symbol} [{task.task_id}] {task.title} (owner: {task.owner_id})")
            
            if task.error_message:
                lines.append(f"{indent_str}    ⚠ Error: {task.error_message}")
            
            # Recursively format children
            for child_id in task.child_ids:
                child = self.tasks.get(child_id)
                if child:
                    format_task(child, level + 1)
        
        if root_id:
            root = self.tasks.get(root_id)
            if root:
                format_task(root, indent)
        else:
            # Format all root tasks
            root_tasks = [t for t in self.tasks.values() if t.parent_id is None]
            for root in root_tasks:
                format_task(root, indent)
        
        return "\n".join(lines) if lines else "No tasks found"