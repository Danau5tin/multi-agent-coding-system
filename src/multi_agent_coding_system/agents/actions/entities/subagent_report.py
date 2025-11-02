"""Data types for subagent communication."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class ContextItem:
    """A single context item to be stored."""
    id: str
    content: str


@dataclass
class SubagentMeta:
    """Metadata for subagent execution."""
    trajectory: Optional[List[Dict[str, Any]]] = None
    num_turns: Optional[int] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0


@dataclass 
class SubagentReport:
    """Structured report from a subagent."""
    contexts: List[ContextItem]
    context_refs: List[str] = field(default_factory=list)  # References to existing contexts
    comments: str = ""
    meta: Optional[SubagentMeta] = None
    
    def to_dict(self):
        """Convert to dictionary format expected by orchestrator hub."""
        result = {
            "contexts": [
                {"id": ctx.id, "content": ctx.content}
                for ctx in self.contexts
            ],
            "comments": self.comments
        }
        if self.meta:
            result["meta"] = {
                "trajectory": self.meta.trajectory,
                "num_turns": self.meta.num_turns,
                "total_input_tokens": self.meta.total_input_tokens,
                "total_output_tokens": self.meta.total_output_tokens
            }
        return result