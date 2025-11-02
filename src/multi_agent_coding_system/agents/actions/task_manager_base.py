"""Abstract base class for task management systems."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from multi_agent_coding_system.agents.actions.entities.task import Task, TaskStatus


class TaskManagerABC(ABC):
    """Abstract base class defining the interface for task management.
    
    This defines the contract that any task manager implementation must follow,
    ensuring consistent API across different implementations.
    """
    
    @abstractmethod
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
        """Create a new root task.
        
        Args:
            title: Brief title for the task
            description: Detailed description of what needs to be done
            owner_id: ID of the agent creating this task
            **kwargs: Additional implementation-specific parameters
            
        Returns:
            The unique ID of the created task
        """
        pass
    
    @abstractmethod
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
        """Create a subtask under an existing parent task.
        
        Args:
            parent_id: ID of the parent task
            title: Brief title for the subtask
            description: Detailed description of what needs to be done
            owner_id: ID of the agent creating this subtask
            **kwargs: Additional implementation-specific parameters
            
        Returns:
            The unique ID of the created subtask
            
        Raises:
            ValueError: If parent_id doesn't exist or depth limit exceeded
            PermissionError: If owner cannot create subtasks under parent
        """
        pass
    
    @abstractmethod
    def update_status(
        self, 
        task_id: str, 
        status: TaskStatus, 
        owner_id: str, 
        error_message: Optional[str] = None
    ) -> bool:
        """Update the status of a task.
        
        Args:
            task_id: ID of the task to update
            status: New status for the task
            owner_id: ID of the agent requesting the update
            error_message: Optional error message if status is failed/completed with error
            
        Returns:
            True if update was successful, False otherwise
            
        Raises:
            PermissionError: If owner_id doesn't own the task
            ValueError: If task_id doesn't exist
        """
        pass
    
    @abstractmethod
    def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a single task by ID.
        
        Args:
            task_id: The ID of the task to retrieve
            
        Returns:
            The Task object if found, None otherwise
        """
        pass
    
    @abstractmethod
    def get_tree(self, root_id: Optional[str] = None) -> Dict:
        """Get hierarchical tree representation of tasks.
        
        Args:
            root_id: Optional ID of root task to get tree from.
                    If None, returns all task trees.
                    
        Returns:
            Dictionary representation of the task tree(s)
        """
        pass
    
    @abstractmethod
    def get_children(self, parent_id: str) -> List[Task]:
        """Get all direct children of a task.
        
        Args:
            parent_id: ID of the parent task
            
        Returns:
            List of child Task objects
        """
        pass
    
    @abstractmethod
    def get_owned_tasks(self, owner_id: str) -> List[Task]:
        """Get all tasks owned by a specific agent.
        
        Args:
            owner_id: ID of the agent
            
        Returns:
            List of Task objects owned by the agent
        """
        pass
    
    @abstractmethod
    def can_modify(self, task_id: str, agent_id: str) -> bool:
        """Check if an agent has permission to modify a task.
        
        Args:
            task_id: ID of the task
            agent_id: ID of the agent
            
        Returns:
            True if agent can modify the task, False otherwise
        """
        pass
    
    @abstractmethod
    def get_all_tasks(self) -> List[Task]:
        """Get all tasks in the system.
        
        Returns:
            List of all Task objects
        """
        pass