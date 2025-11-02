"""Time utilities for tracking and formatting elapsed time."""

import time
from typing import Optional, Tuple


def format_elapsed_time(start_time: Optional[float]) -> Tuple[int,int]:
    if not start_time:
        return 0, 0

    elapsed_seconds = int(time.time() - start_time)
    elapsed_minutes = elapsed_seconds // 60
    elapsed_secs = elapsed_seconds % 60

    return elapsed_minutes, elapsed_secs

def format_elapsed_time_with_prefix(start_time: Optional[float], prefix: str = "## Total Session Time Elapsed:\n") -> str:
    """Format elapsed time with a customizable prefix.

    Args:
        start_time: Unix timestamp of when the task started.
                   If None, returns empty string.
        prefix: String to prepend to the formatted time (default: "\n## ")

    Returns:
        Formatted string like "\n## Time Elapsed: 05:23" or empty string if no start_time.
    """
    mins, secs = format_elapsed_time(start_time)
    if start_time:
        return f"{prefix}{mins:02d}:{secs:02d}"
    return ""