from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, Optional

@dataclass
class Context:
    """Represents a piece of reusable context information."""
    id: str
    content: str
    reported_by: str  # 'techlead' or task_id
    task_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
