from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from multi_agent_coding_system.agents.actions.entities.actions import Action

@dataclass
class ExecutionResult:
    """Result of executing a single LLM response."""
    actions_executed: List[Action]
    env_responses: List[str]  # Only responses that should be shown in history
    has_error: bool
    finish_message: Optional[str] = None
    done: bool = False  # True if FinishAction was executed
    subagent_trajectories: Optional[Dict[str, Dict[str, Any]]] = None
    has_parsing_error: bool = False  # True if parsing errors occurred
    duplicate_contexts_count: int = 0  # Number of duplicate contexts from subagents
    successful_context_refs: int = 0  # Number of context_refs that successfully resolved
    missing_context_refs: int = 0  # Number of context_refs that didn't resolve
    
    def to_dict(self) -> dict:
        """Convert execution result to dictionary format."""
        result = {
            "actions_executed": [action.to_dict() for action in self.actions_executed],
            "env_responses": self.env_responses,
            "has_error": self.has_error,
            "has_parsing_error": self.has_parsing_error,
            "finish_message": self.finish_message,
            "done": self.done
        }
        if self.subagent_trajectories:
            result["subagent_trajectories"] = self.subagent_trajectories
        return result

    def to_user_msg_content(self) -> str:
        env_response = "\n".join(self.env_responses)
        return env_response
