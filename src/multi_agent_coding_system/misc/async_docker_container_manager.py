import aiodocker
from aiodocker.exceptions import DockerError
import os
from typing import Tuple, Dict, Any, Optional
import tarfile
import io
import logging
import asyncio
import aiofiles
from pathlib import Path


logger = logging.getLogger(__name__)

class AsyncDockerContainerManager:
    def __init__(self, docker_endpoints: Optional[list[str]] = None):
        """
        Initialize the async Docker container manager.

        Args:
            docker_endpoints: List of Docker daemon endpoints (e.g., ["unix:///var/run/docker.sock", "tcp://10.15.25.9:2375"])
                            If None, reads from DOCKER_ENDPOINTS env var (comma-separated)
                            If no endpoints provided, defaults to local Unix socket
        """
        # Parse docker endpoints
        if docker_endpoints is None:
            endpoints_env = os.environ.get("DOCKER_ENDPOINTS", "")
            if endpoints_env:
                docker_endpoints = [ep.strip() for ep in endpoints_env.split(",")]
            else:
                docker_endpoints = ["unix:///var/run/docker.sock"]

        self.docker_endpoints = docker_endpoints
        self.clients: list[aiodocker.Docker] = []
        self.containers: Dict[str, tuple[int, Any]] = {}  # container_id -> (node_index, container_obj)
        self.active_container_counts: list[int] = []  # Track active containers per node
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
        self._node_selection_lock = asyncio.Lock()  # Lock for thread-safe node selection

        # Legacy compatibility
        self.client: Optional[aiodocker.Docker] = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup_all()
        await asyncio.gather(*[client.close() for client in self.clients], return_exceptions=True)

    async def _ensure_initialized(self):
        """Ensure all clients are initialized."""
        if not self._initialized:
            # Initialize a Docker client for each endpoint
            for endpoint in self.docker_endpoints:
                client = aiodocker.Docker(url=endpoint)
                self.clients.append(client)
                self.active_container_counts.append(0)

            # Set legacy client to first client for backward compatibility
            self.client = self.clients[0] if self.clients else None
            self._initialized = True

            self.logger.info(f"Initialized Docker manager with {len(self.clients)} node(s): {self.docker_endpoints}")

    def _select_least_loaded_node(self) -> int:
        """
        Select the node with the fewest active containers.

        Returns:
            Index of the least loaded node
        """
        return self.active_container_counts.index(min(self.active_container_counts))

    async def _log_container_startup_failure(
        self, container: Any, node_idx: int, image_name: str, container_info: Dict[str, Any]
    ) -> None:
        self.logger.error(f"Container startup failure for image {image_name}:")
        self.logger.error(f"  Node: {node_idx} ({self.docker_endpoints[node_idx]})")
        self.logger.error(f"  Container ID: {container.id}")
        self.logger.error(f"  Status: {container_info['State']['Status']}")
        self.logger.error(f"  Error: {container_info['State'].get('Error', 'N/A')}")
        self.logger.error(f"  ExitCode: {container_info['State'].get('ExitCode', 'N/A')}")

        # Try to get container logs for more context
        try:
            logs = await container.log(stdout=True, stderr=True, tail=50)
            if logs:
                log_output = ''.join(logs)
                self.logger.error(f"  Container logs (last 50 lines):\n{log_output}")
        except Exception as log_err:
            self.logger.error(f"  Could not retrieve container logs: {log_err}")

    def _log_container_creation_failure(
        self, e: Exception, node_idx: int, image_name: str
    ) -> None:
        self.logger.error(f"Failed to create/start container for image {image_name}:")
        self.logger.error(f"  Node: {node_idx} ({self.docker_endpoints[node_idx]})")
        self.logger.error(f"  Exception type: {type(e).__name__}")
        self.logger.error(f"  Exception message: {str(e)}")

        # If it's a DockerError, try to extract more details
        if isinstance(e, DockerError):
            self.logger.error(f"  Docker error details: {e}")
            if hasattr(e, 'message'):
                self.logger.error(f"  Docker message: {e.message}")

    async def _get_container(self, container_id: str) -> tuple[int, Any]:
        """
        Get a container by ID, fetching from Docker if needed.

        Args:
            container_id: The ID of the container

        Returns:
            Tuple of (node_index, container_object)
        """
        await self._ensure_initialized()
        try:
            if container_id not in self.containers:
                # Try to find the container on any node
                for node_idx, client in enumerate(self.clients):
                    try:
                        container = await client.containers.get(container_id)
                        self.containers[container_id] = (node_idx, container)
                        break
                    except DockerError:
                        continue
                else:
                    raise DockerError(None, {"message": f"Container {container_id} not found on any node"})

            return self.containers[container_id]
        except DockerError:
            # Container doesn't exist, clean up reference if we have it
            if container_id in self.containers:
                del self.containers[container_id]
            raise

    async def spin_up_container_from_dir(self, build_context_dir: str, image_name: str = '') -> str:
        """
        Build and run a Docker container from a directory containing a Dockerfile.
        Automatically selects the least-loaded node for multi-node setups.

        Args:
            image_name: name for the Docker image (defaults to subdirectory name if not provided)
            build_context_dir: Path to directory containing Dockerfile and any files it references

        Returns:
            The container ID
        """
        await self._ensure_initialized()

        # Validate the directory exists and has a Dockerfile
        build_path = Path(build_context_dir)
        if not build_path.exists():
            raise ValueError(f"Build context directory does not exist: {build_context_dir}")

        dockerfile_path = build_path / "Dockerfile"
        if not dockerfile_path.exists():
            raise ValueError(f"No Dockerfile found in: {build_context_dir}")

        # Use subdirectory name as image name if not provided
        if not image_name:
            image_name = os.path.basename(os.path.abspath(build_context_dir))

        # Select the least loaded node (with lock to prevent race conditions in concurrent creation)
        async with self._node_selection_lock:
            node_idx = self._select_least_loaded_node()
            # Increment counter immediately to reserve this slot
            self.active_container_counts[node_idx] += 1

        client = self.clients[node_idx]

        self.logger.debug(f"Selected node {node_idx} (endpoint: {self.docker_endpoints[node_idx]}) with {self.active_container_counts[node_idx]} active containers")

        try:
            # Build the image - Docker handles concurrency internally
            try:
                # First attempt with cache
                self.logger.debug(f"Building image {image_name} on node {node_idx} with cache")
                await self._build_image(build_context_dir, image_name, node_idx, nocache=False)
            except DockerError as e:
                error_msg = str(e)
                if "unknown parent image ID" in error_msg or "no such image" in error_msg:
                    self.logger.warning(f"Build cache corrupted for {image_name} on node {node_idx}, rebuilding without cache...")

                    # Try to remove the specific image if it exists (might be corrupted)
                    try:
                        images = await client.images.list()
                        for img in images:
                            if image_name in (img.get('RepoTags') or []):
                                await client.images.delete(img['Id'], force=True)
                                self.logger.debug(f"Removed potentially corrupted image: {image_name}")
                                break
                    except Exception as img_err:
                        self.logger.debug(f"Could not remove image {image_name}: {img_err}")

                    # Clear only dangling images and minimal build cache
                    try:
                        # Remove dangling images (those without tags)
                        await self._run_command(["docker", "image", "prune", "-f"], check=False)
                        # Only prune build cache without --all flag (keeps actively used layers)
                        await self._run_command(["docker", "builder", "prune", "-f"], check=False)
                    except Exception as cleanup_err:
                        self.logger.debug(f"Cache cleanup error (continuing anyway): {cleanup_err}")

                    # Retry without cache
                    await self._build_image(build_context_dir, image_name, node_idx, nocache=True)
                else:
                    raise

            # Run the container (each caller gets their own container)
            container = await client.containers.create(
                config={
                    'Image': image_name,
                    'AttachStdin': True,
                    'AttachStdout': True,
                    'AttachStderr': True,
                    'Tty': True,
                    'OpenStdin': True,
                    'StdinOnce': False,
                    'Cmd': ['/bin/bash'],  # Keep container running with bash
                },
                name=None
            )

            await container.start()

            # Wait a moment for container to fully start
            await asyncio.sleep(0.5)

            # Check if container is running
            container_info = await container.show()
            if container_info['State']['Status'] != 'running':
                error_msg = f"Container failed to start on node {node_idx}. Status: {container_info['State']['Status']}"
                if container_info['State'].get('Error'):
                    error_msg += f", Error: {container_info['State']['Error']}"
                if container_info['State'].get('ExitCode'):
                    error_msg += f", ExitCode: {container_info['State']['ExitCode']}"

                # Log detailed failure information
                await self._log_container_startup_failure(container, node_idx, image_name, container_info)

                raise RuntimeError(error_msg)

            # Store the container reference
            container_id = container.id
            if container_id is None:
                raise RuntimeError("Container was created but has no ID")

            self.containers[container_id] = (node_idx, container)

            self.logger.debug(f"Container {container_id} started successfully on node {node_idx} for image {image_name}")

            return container_id

        except Exception as e:
            # If container creation failed, decrement the counter
            async with self._node_selection_lock:
                self.active_container_counts[node_idx] -= 1

            # Log detailed error information
            self._log_container_creation_failure(e, node_idx, image_name)

            raise

    async def _build_image(self, build_context_dir: str, image_name: str, node_idx: int, nocache: bool = False):
        # NOTE: This method uses subprocess to leverage Docker CLI BuildKit support which aiodocker lacks.

        cmd = ["docker", "build", "-t", image_name]

        if nocache:
            cmd.append("--no-cache")

        cmd.extend(["--rm", "--force-rm", build_context_dir])

        env = os.environ.copy()
        env["DOCKER_BUILDKIT"] = "1"

        endpoint = self.docker_endpoints[node_idx]
        if endpoint.startswith("tcp://"):
            env["DOCKER_HOST"] = endpoint
        elif endpoint.startswith("unix://"):
            env["DOCKER_HOST"] = endpoint

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            # Stream output in real-time
            async def read_stream(stream, prefix=""):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace').strip()
                    if decoded:
                        self.logger.debug(f"{prefix}{decoded}")

            # Read both stdout and stderr concurrently with 10-minute timeout
            async def build_with_timeout():
                await asyncio.gather(
                    read_stream(process.stdout),
                    read_stream(process.stderr, "[ERROR] ")
                )
                await process.wait()

            try:
                await asyncio.wait_for(build_with_timeout(), timeout=600)  # 10 minute timeout
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                error_msg = f"Build timed out after 600 seconds"
                self.logger.error(f"Build failed for {image_name}: {error_msg}")
                raise DockerError(None, {'message': error_msg})

            if process.returncode != 0:
                error_msg = f"Build failed with exit code {process.returncode}"
                self.logger.error(f"Build failed for {image_name}: {error_msg}")
                raise DockerError(None, {'message': error_msg})

            self.logger.debug(f"Build completed successfully for {image_name}")

        except asyncio.TimeoutError:
            # Re-raise timeout errors from wait_for
            raise
        except Exception as e:
            self.logger.error(f"Build failed for {image_name}. Error: {str(e)}")
            raise

    async def close_container(self, container_id: str) -> None:
        """
        Stop and remove a Docker container.

        Args:
            container_id: The ID of the container to close
        """
        await self._ensure_initialized()
        try:
            node_idx, container = await self._get_container(container_id)
            if container:
                try:
                    await container.stop(t=10)
                except DockerError:
                    pass  # Container already stopped

                try:
                    await container.delete(force=True)
                except DockerError:
                    pass  # Container already removed

                # Update active container count
                self.active_container_counts[node_idx] -= 1

                # Clean up our reference
                if container_id in self.containers:
                    del self.containers[container_id]
        except DockerError:
            # Container doesn't exist
            pass

    async def copy_file_to_container(self, container_id: str, local_file_path: str, container_file_path: str) -> None:
        """
        Copy a file from the local filesystem to a Docker container.

        Args:
            container_id: The ID of the container
            local_file_path: The path to the file on the local filesystem
            container_file_path: The destination path in the container
        """
        await self._ensure_initialized()
        node_idx, container = await self._get_container(container_id)
        if not container:
            raise ValueError(f"Container {container_id} not found")

        # Read the local file asynchronously
        async with aiofiles.open(local_file_path, 'rb') as f:
            file_data = await f.read()

        # Create a tar archive in memory (use thread pool for CPU-bound operation)
        tar_data = await asyncio.get_event_loop().run_in_executor(
            None, self._create_file_tar_archive, file_data, container_file_path
        )

        # Copy the tar archive to the container
        await container.put_archive(
            path=os.path.dirname(container_file_path) or '/',
            data=tar_data
        )

    async def execute_command(self, container_id: str, command: str, timeout: Optional[int] = None, **exec_kwargs) -> Tuple[str, str]:
        """
        Execute a bash command in a Docker container.

        Args:
            container_id: The ID of the container
            command: The bash command to execute
            timeout: Optional timeout in seconds for the command execution
            **exec_kwargs: Additional keyword arguments to pass to exec_run
                          (e.g., environment, workdir, user)

        Returns:
            A tuple of (stdout, stderr)
        """
        await self._ensure_initialized()
        node_idx, container = await self._get_container(container_id)
        if not container:
            raise ValueError(f"Container {container_id} not found")

        # Check if container is running
        try:
            container_info = await container.show()
            if container_info['State']['Status'] != 'running':
                raise RuntimeError(f"Container {container_id} is not running. Status: {container_info['State']['Status']}")
        except DockerError as e:
            raise RuntimeError(f"Failed to check container status: {e}")

        # Prepare the command as expected by aiodocker
        cmd = ['bash', '-c', command]

        # Prepare exec parameters using aiodocker's API
        exec_params = {
            'cmd': cmd,
            'stdout': True,
            'stderr': True,
            'tty': False,
        }

        # Map common exec_kwargs to aiodocker format
        if 'environment' in exec_kwargs:
            # Convert dict to list of "key=value" strings
            exec_params['environment'] = [f"{k}={v}" for k, v in exec_kwargs.pop('environment').items()]
        if 'workdir' in exec_kwargs:
            exec_params['workdir'] = exec_kwargs.pop('workdir')
        if 'user' in exec_kwargs:
            exec_params['user'] = exec_kwargs.pop('user')

        # Use the simpler approach - exec returns an Exec instance
        exec_instance = await container.exec(**exec_params)

        # Start the execution - returns a Stream object
        stream = exec_instance.start(detach=False)

        # Collect output - read Message objects from stream
        stdout_chunks = []
        stderr_chunks = []

        async def read_stream():
            """Read all output from the stream."""
            async with stream:
                while True:
                    msg = await stream.read_out()
                    if msg is None:
                        break
                    # Message has .stream (1=stdout, 2=stderr) and .data (bytes)
                    if hasattr(msg, 'stream') and hasattr(msg, 'data'):
                        if msg.stream == 1:  # stdout
                            stdout_chunks.append(msg.data.decode('utf-8', errors='replace'))
                        elif msg.stream == 2:  # stderr
                            stderr_chunks.append(msg.data.decode('utf-8', errors='replace'))
                    elif isinstance(msg, bytes):
                        # Fallback for simple bytes response
                        stdout_chunks.append(msg.decode('utf-8', errors='replace'))

        # Apply timeout to the actual command execution (stream reading)
        if timeout is not None:
            await asyncio.wait_for(read_stream(), timeout=timeout)
        else:
            await read_stream()

        # Join the chunks
        stdout = ''.join(stdout_chunks)
        stderr = ''.join(stderr_chunks)

        return stdout, stderr

    async def cleanup_all(self) -> None:
        """
        Stop and remove all managed containers.
        """
        await self._ensure_initialized()
        container_ids = list(self.containers.keys())
        tasks = [self.close_container(container_id) for container_id in container_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def docker_system_cleanup(self) -> None:
        """
        Clean up Docker resources (containers, networks, images, build cache).
        """
        logger.debug("Running Docker cleanup...")

        # Clean up stopped containers
        stopped_containers = await self._run_command(
            ["docker", "ps", "-a", "--filter", "status=exited", "--filter", "status=dead", "-q"]
        )
        if stopped_containers.strip():
            container_count = len(stopped_containers.strip().split('\n'))
            logger.info(f"Removing {container_count} stopped containers")
            await self._run_command(["docker", "container", "prune", "-f"])

        # Count networks before cleanup
        networks_before = await self._run_command(["docker", "network", "ls", "-q"])
        network_count_before = len(networks_before.strip().split('\n')) if networks_before.strip() else 0

        # Remove ALL unused networks (docker network prune handles this safely)
        await self._run_command(["docker", "network", "prune", "-f"])

        # Count networks after cleanup
        networks_after = await self._run_command(["docker", "network", "ls", "-q"])
        network_count_after = len(networks_after.strip().split('\n')) if networks_after.strip() else 0
        networks_removed = network_count_before - network_count_after

        if networks_removed > 0:
            logger.info(f"Removed {networks_removed} unused networks")

        # Clean up ALL unused images (safe - won't remove images used by running containers)
        # Images will be rebuilt from Dockerfile when needed
        image_cleanup_output = await self._run_command(["docker", "image", "prune", "-a", "-f"])
        if "Total reclaimed space:" in image_cleanup_output:
            for line in image_cleanup_output.split('\n'):
                if "Total reclaimed space:" in line:
                    logger.info(f"Image cleanup: {line.strip()}")

        # Clean up build cache (removes dangling build cache)
        build_cleanup_output = await self._run_command(["docker", "builder", "prune", "-f"])
        if "Total reclaimed space:" in build_cleanup_output:
            for line in build_cleanup_output.split('\n'):
                if "Total reclaimed space:" in line:
                    logger.info(f"Build cache cleanup: {line.strip()}")

        logger.debug("Docker cleanup completed")

    async def _run_command(self, cmd: list, check: bool = True) -> str:
        """Run a command and return output."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"Command timed out: {' '.join(cmd)}")
                return ""

            if check and process.returncode != 0:
                logger.error(f"Command failed: {' '.join(cmd)}: {stderr.decode()}")
                return ""

            return stdout.decode()
        except Exception as e:
            if check:
                logger.error(f"Command failed: {' '.join(cmd)}: {e}")
            return ""

    def _create_tar_archive(self, build_context_dir: str) -> io.BytesIO:
        """Create tar archive synchronously (runs in thread pool)."""
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w:gz') as tar:
            for root, dirs, files in os.walk(build_context_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, build_context_dir)
                    tar.add(file_path, arcname=arcname)
        tar_stream.seek(0)
        return tar_stream

    def _create_file_tar_archive(self, file_data: bytes, container_file_path: str) -> bytes:
        """Create tar archive for a single file (runs in thread pool)."""
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            tarinfo = tarfile.TarInfo(name=os.path.basename(container_file_path))
            tarinfo.size = len(file_data)
            tar.addfile(tarinfo, io.BytesIO(file_data))
        tar_stream.seek(0)
        return tar_stream.read()

    async def close(self):
        """
        Close all Docker clients and cleanup resources.
        """
        await self.cleanup_all()
        await asyncio.gather(*[client.close() for client in self.clients], return_exceptions=True)
        self.clients = []
        self.client = None
        self._initialized = False

    def __del__(self):
        """
        Cleanup when the manager is destroyed.
        Note: This is synchronous cleanup for compatibility.
        For proper async cleanup, use async context manager or call close() explicitly.
        """
        if self.client:
            # Schedule cleanup in event loop if available
            try:
                loop = asyncio.get_event_loop()
                if loop and not loop.is_closed():
                    asyncio.create_task(self.close())
            except (RuntimeError, TypeError):
                # No event loop available or other error
                # Don't log here as logging may be shut down
                pass


# Create a singleton instance for module-level usage
# Note: For async usage, prefer creating instances with async context manager
async def get_async_docker_manager():
    """Factory function to get an initialized async docker manager."""
    manager = AsyncDockerContainerManager()
    await manager._ensure_initialized()
    return manager