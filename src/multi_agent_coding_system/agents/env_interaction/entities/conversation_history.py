from typing import List
from dataclasses import dataclass, field

from multi_agent_coding_system.agents.env_interaction.entities.turn import Turn

@dataclass
class ConversationHistory:
    """Manages conversation history for state tracking."""
    turns: List[Turn] = field(default_factory=list)
    max_turns: int = 100  # Keep last N turns to avoid context explosion
    
    def add_turn(self, turn: Turn):
        """Add a turn to history, maintaining max size."""
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]
    
    def to_prompt(self) -> str:
        """Convert history to prompt format."""
        if not self.turns:
            return "No previous interactions."
        
        turn_strs = []
        for i, turn in enumerate(self.turns, 1):
            turn_strs.append(f"--- Turn {i} ---\n{turn.to_prompt()}")
        
        return "\n\n".join(turn_strs)


    def to_dict(self) -> List[dict]:
        """Convert history to a list of dicts for structured logging."""
        return [turn.to_dict() for turn in self.turns]
