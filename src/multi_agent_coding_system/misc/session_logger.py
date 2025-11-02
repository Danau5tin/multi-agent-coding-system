"""Session-based logger for tracking orchestrator and subagent execution in a single file."""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import aiofiles
import asyncio
from dataclasses import dataclass, asdict, field
from enum import Enum

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    SUBAGENT = "subagent"
    ORCA_ENV = "orca_env"


@dataclass
class SubagentSession:
    """Represents a subagent's execution within a turn."""
    agent_id: str
    agent_type: str  # "explorer" or "coder"
    task_title: str
    task_description: str
    max_turns: int
    turns: List[Dict[str, Any]] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    completed: bool = False
    report: Optional[Dict[str, Any]] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def add_turn(self, llm_output: str, env_response: str, actions: List[str] = None):
        """Add a turn to the subagent session."""
        turn = {
            "turn_number": len(self.turns) + 1,
            "timestamp": datetime.now().isoformat(),
            "llm_output": llm_output,
            "env_response": env_response,
            "actions": actions or []
        }
        self.turns.append(turn)

    def finish(self, report: Dict[str, Any] = None):
        """Mark the subagent session as finished."""
        self.end_time = datetime.now().isoformat()
        self.completed = True
        if report:
            self.report = report


@dataclass
class Turn:
    """Represents a single turn in the main session."""
    turn_number: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    llm_output: str = ""
    env_response: str = ""
    actions: List[str] = field(default_factory=list)
    subagent_sessions: List[SubagentSession] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_subagent_session(self, session: SubagentSession):
        """Add a subagent session to this turn."""
        self.subagent_sessions.append(session)


@dataclass
class Session:
    """Represents a complete execution session."""
    session_id: str
    agent_type: AgentType
    task: str
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    turns: List[Turn] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    finish_reason: Optional[str] = None
    total_turns: int = 0

    def add_turn(self, turn: Turn):
        """Add a turn to the session."""
        self.turns.append(turn)
        self.total_turns = len(self.turns)

    def finish(self, reason: str = "completed"):
        """Mark the session as finished."""
        self.end_time = datetime.now().isoformat()
        self.completed = True
        self.finish_reason = reason


class SessionLogger:
    """Manages session logging to a single JSON file."""

    def __init__(self, logging_dir: Optional[Path], session_id: str, agent_type: AgentType = AgentType.ORCA_ENV):
        """Initialize the session logger.

        Args:
            logging_dir: Directory to write logs to (None to disable logging)
            session_id: Unique identifier for this session
            agent_type: Type of agent (orchestrator, subagent, or orca_env)
        """
        self.logging_dir = logging_dir
        self.session_id = session_id
        self.agent_type = agent_type
        self.enabled = logging_dir is not None
        self.session: Optional[Session] = None
        self.current_turn: Optional[Turn] = None
        self.file_path: Optional[Path] = None
        self._lock = asyncio.Lock()

        if self.enabled:
            self.logging_dir = Path(logging_dir)
            self.logging_dir.mkdir(exist_ok=True, parents=True)
            self.file_path = self.logging_dir / f"{session_id}_session.json"

    async def start_session(self, task: str, metadata: Dict[str, Any] = None):
        """Start a new session."""
        if not self.enabled:
            return

        async with self._lock:
            self.session = Session(
                session_id=self.session_id,
                agent_type=self.agent_type,
                task=task,
                metadata=metadata or {}
            )
            await self._save_session()

    async def start_turn(self, turn_number: int) -> Turn:
        """Start a new turn in the session."""
        if not self.enabled or not self.session:
            return Turn(turn_number=turn_number)

        async with self._lock:
            self.current_turn = Turn(turn_number=turn_number)
            return self.current_turn

    async def update_turn(self,
                         llm_output: str = None,
                         env_response: str = None,
                         actions: List[str] = None,
                         metadata: Dict[str, Any] = None):
        """Update the current turn with new information."""
        if not self.enabled or not self.current_turn:
            return

        async with self._lock:
            if llm_output:
                self.current_turn.llm_output = llm_output
            if env_response:
                self.current_turn.env_response = env_response
            if actions:
                self.current_turn.actions = actions
            if metadata:
                self.current_turn.metadata.update(metadata)

    async def add_subagent_session(self, subagent_session: SubagentSession):
        """Add a subagent session to the current turn."""
        if not self.enabled or not self.current_turn:
            return

        async with self._lock:
            self.current_turn.add_subagent_session(subagent_session)

    async def end_turn(self):
        """End the current turn and add it to the session."""
        if not self.enabled or not self.session or not self.current_turn:
            return

        async with self._lock:
            self.session.add_turn(self.current_turn)
            self.current_turn = None
            await self._save_session()

    async def end_session(self, reason: str = "completed"):
        """End the session."""
        if not self.enabled or not self.session:
            return

        async with self._lock:
            # Add any remaining turn
            if self.current_turn:
                self.session.add_turn(self.current_turn)
                self.current_turn = None

            self.session.finish(reason)
            await self._save_session()

    async def _save_session(self):
        """Save the current session to file."""
        if not self.enabled or not self.session or not self.file_path:
            return

        try:
            # Convert session to dict, handling dataclasses
            session_dict = self._session_to_dict(self.session)

            # Write to file
            async with aiofiles.open(self.file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(session_dict, indent=2, ensure_ascii=False))

            logger.debug(f"Saved session to {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    def _session_to_dict(self, obj: Any) -> Any:
        """Recursively convert dataclasses to dicts."""
        if isinstance(obj, (Session, Turn, SubagentSession)):
            return {k: self._session_to_dict(v) for k, v in asdict(obj).items()}
        elif isinstance(obj, list):
            return [self._session_to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._session_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, Enum):
            return obj.value
        else:
            return obj

    async def log_subagent_turn(self,
                                agent_id: str,
                                agent_type: str,
                                turn_num: int,
                                llm_output: str,
                                env_response: str,
                                actions: List[str] = None):
        """Helper method to log a subagent turn within the current main turn."""
        if not self.enabled:
            return

        # This would be called by subagents to update their session within a turn
        # Implementation would depend on how subagents are tracked
        pass


class SubagentSessionTracker:
    """Helper class for tracking a subagent's session within a parent turn."""

    def __init__(self, parent_logger: SessionLogger, agent_id: str, agent_type: str,
                 task_title: str, task_description: str, max_turns: int):
        """Initialize the subagent session tracker."""
        self.parent_logger = parent_logger
        self.session = SubagentSession(
            agent_id=agent_id,
            agent_type=agent_type,
            task_title=task_title,
            task_description=task_description,
            max_turns=max_turns
        )

    async def add_turn(self, llm_output: str, env_response: str, actions: List[str] = None):
        """Add a turn to the subagent session."""
        self.session.add_turn(llm_output, env_response, actions)

    async def finish(self, report: Dict[str, Any] = None,
                    total_input_tokens: int = 0,
                    total_output_tokens: int = 0):
        """Finish the subagent session and add it to the parent logger."""
        self.session.total_input_tokens = total_input_tokens
        self.session.total_output_tokens = total_output_tokens
        self.session.finish(report)

        # Add to parent logger's current turn
        if self.parent_logger:
            await self.parent_logger.add_subagent_session(self.session)