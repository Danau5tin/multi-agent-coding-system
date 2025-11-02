"""Command execution abstraction for both Docker and Tmux environments."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Tuple

logger = logging.getLogger(__name__)


class CommandExecutor(ABC):
    """Abstract base class for command execution in different environments."""

    @abstractmethod
    async def execute(self, cmd: str, timeout: int = 30) -> Tuple[str, int]:
        """Execute a command and return (output, return_code)."""

    @abstractmethod
    async def execute_background(self, cmd: str) -> None:
        """Execute a command in background."""


class DockerExecutor(CommandExecutor):
    """Execute commands using docker exec or AsyncDockerContainerManager."""

    def __init__(self, container_name: str, docker_manager=None):
        """Initialize DockerExecutor.

        Args:
            container_name: The container ID or name
            docker_manager: Optional AsyncDockerContainerManager for multi-node support
        """
        self.container_name = container_name
        self.docker_manager = docker_manager

    async def execute(self, cmd: str, timeout: int = 30) -> Tuple[str, int]:
        """Execute a command in the Docker container and return (output, return_code)."""
        # If docker_manager is provided, use it (multi-node aware)
        if self.docker_manager:
            try:
                stdout, stderr = await self.docker_manager.execute_command(
                    container_id=self.container_name,
                    command=cmd,
                    timeout=timeout
                )
                # Combine stdout and stderr like the legacy approach
                output = stdout + stderr
                # AsyncDockerContainerManager doesn't return exit codes directly
                # So we infer: if stderr is empty, assume success
                exit_code = 0 if not stderr else 1
                return output, exit_code
            except Exception as e:
                return f"Error executing command: {str(e)}", 1

        # Legacy approach: use docker exec subprocess (for pre-created containers)
        try:
            proc = await asyncio.create_subprocess_exec(
                'docker', 'exec', self.container_name, 'bash', '-c', cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
                output = stdout.decode('utf-8', errors='replace') if stdout else ""
                exit_code = proc.returncode or 0
                return output, exit_code
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Command timed out after {timeout} seconds", 124  # 124 is the standard timeout exit code

        except Exception as e:
            return f"Error executing command: {str(e)}", 1

    async def execute_background(self, cmd: str) -> None:
        """Execute a command in background in the Docker container.

        Note: Errors are logged but not raised since background tasks
        are fire-and-forget by design.
        """
        # If docker_manager is provided, use it (multi-node aware)
        if self.docker_manager:
            try:
                # For background execution with AsyncDockerContainerManager,
                # we just fire-and-forget using execute_command
                # We could wrap this in asyncio.create_task() but that would
                # create a detached task. Instead, we'll execute it and not wait for completion.
                asyncio.create_task(
                    self.docker_manager.execute_command(
                        container_id=self.container_name,
                        command=f"nohup {cmd} > /dev/null 2>&1 &"
                    )
                )
            except Exception as e:
                logger.error(f"Failed to start background command: {e}", exc_info=True)
            return

        # Legacy approach: use docker exec subprocess (for pre-created containers)
        try:
            proc = await asyncio.create_subprocess_exec(
                'docker', 'exec', '-d', self.container_name, 'bash', '-c', cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            # Wait briefly to ensure the process started successfully
            # This catches immediate failures (e.g., docker not found, container doesn't exist)
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.1)
                # If it completes this quickly, it likely failed
                if proc.returncode != 0:
                    logger.warning(f"Background command may have failed immediately: {cmd[:50]}...")
            except asyncio.TimeoutError:
                # This is expected - the process is still running in background
                pass
        except Exception as e:
            # Log the error but don't raise it since background tasks are fire-and-forget
            logger.error(f"Failed to start background command: {e}", exc_info=True)
