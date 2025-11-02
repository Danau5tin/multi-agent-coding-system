import os
from pathlib import Path
from functools import lru_cache

LATEST_SYSTEM_MSGS = {
    "orchestrator": "orchestrator_sys_msg.md",
    "explorer": "explorer_sys_msg.md",
    "coder": "coder_sys_msg.md",
}

cwd = os.getcwd()
this_dir_path: Path = Path(__file__).parent.resolve()
system_msgs_dir = Path(this_dir_path) / "md_files"


@lru_cache(maxsize=None)
def _load_system_message(agent_type: str) -> str:
    if agent_type not in LATEST_SYSTEM_MSGS:
        raise ValueError(f"Unknown agent type: {agent_type}")

    file_name = LATEST_SYSTEM_MSGS[agent_type]
    file_path = system_msgs_dir / file_name

    if not file_path.exists():
        raise FileNotFoundError(f"System message file not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def load_orchestrator_system_message() -> str:
    return _load_system_message("orchestrator")


def load_explorer_system_message(depth: int) -> str:
    return _load_system_message("explorer")


def load_coder_system_message(depth: int) -> str:
    return _load_system_message("coder")
