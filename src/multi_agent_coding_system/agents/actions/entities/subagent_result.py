"""Data class for subagent execution results."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class SubagentResult:
    """Result from executing a subagent task."""
    task_id: str
    context_ids_stored: List[str] = field(default_factory=list)
    comments: str = ""
    error: Optional[str] = None
    duplicate_contexts_count: int = 0  # Number of duplicate contexts in the report

    @property
    def has_error(self) -> bool:
        """Check if the result contains an error."""
        return self.error is not None

    @property
    def success(self) -> bool:
        """Check if the result was successful."""
        return self.error is None


@dataclass
class VerboseSubagentResult(SubagentResult):
    """Extended result that includes full context content for verbose output."""
    contexts: Dict[str, str] = field(default_factory=dict)  # Maps context_id -> content