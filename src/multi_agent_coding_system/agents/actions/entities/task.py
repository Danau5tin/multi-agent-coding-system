from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class TaskStatus(Enum):
    """Task lifecycle states."""
    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ContextBootstrapItem:
    """A file or directory to be read into subagent context."""
    path: str
    reason: str


@dataclass
class Task:
    """Represents a task to be executed by a subagent."""
    task_id: str
    agent_type: Literal['explorer', 'coder']
    title: str
    description: str
    max_turns: int
    context_refs: List[str] = field(default_factory=list)
    context_bootstrap: List[ContextBootstrapItem] = field(default_factory=list)
    status: TaskStatus = TaskStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    
    # Hierarchical fields
    parent_id: Optional[str] = None
    child_ids: List[str] = field(default_factory=list)
    owner_id: str = ""  # The agent that created this task
    depth: int = 0
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary representation."""
        data = asdict(self)
        data['status'] = self.status.value
        data['context_bootstrap'] = [
            {'path': item.path, 'reason': item.reason} 
            for item in self.context_bootstrap
        ]
        return data
