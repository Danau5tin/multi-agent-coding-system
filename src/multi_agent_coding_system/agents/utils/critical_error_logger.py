"""Critical error logger for tracking and persisting system failures."""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import asyncio
import aiofiles
from pydantic import BaseModel, Field


class CriticalErrorReport(BaseModel):
    error_type: str = Field(
        ...,
        description="One-word identifier for the error type (e.g., 'container_startup_failure')"
    )
    message: str = Field(
        ...,
        description="Error message or exception details"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context like task_id, container_id, etc."
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO format timestamp (auto-generated if not provided)"
    )

    def model_post_init(self, context: Any, /) -> None:
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


class CriticalErrorLogger:
    """Async logger for critical system errors."""

    def __init__(self, output_dir: Optional[str] = None):
        if output_dir is None:
            base_dir = os.environ.get("OUTPUT_DIR", ".")
            output_dir = os.path.join(base_dir, "critical_errors")

        self.output_dir = Path(output_dir)
        self._write_lock = asyncio.Lock()

    async def _ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def log_error(self, report: CriticalErrorReport) -> Path:
        """Log a critical error report to disk.

        Args:
            report: The error report to log

        Returns:
            Path to the created log file
        """
        async with self._write_lock:
            await self._ensure_output_dir()

            # Generate filename: DD_MM_HH_SS_<error_type>.json
            now = datetime.now()
            filename = f"{now.strftime('%d_%m_%H_%S')}_{report.error_type}.json"
            file_path = self.output_dir / filename

            # Write report to file asynchronously
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(
                    json.dumps(report.model_dump(), indent=2, ensure_ascii=False)
                )

            return file_path


# Global singleton instance
_global_logger: Optional[CriticalErrorLogger] = None


def get_critical_error_logger(output_dir: Optional[str] = None) -> CriticalErrorLogger:
    """Get or create the global critical error logger instance.

    Args:
        output_dir: Directory to store error logs (only used on first call)

    Returns:
        Global CriticalErrorLogger instance
    """
    global _global_logger
    if _global_logger is None:
        _global_logger = CriticalErrorLogger(output_dir=output_dir)
    return _global_logger
