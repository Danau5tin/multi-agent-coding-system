import asyncio
import tempfile
import os
import shutil

from multi_agent_coding_system.misc.async_docker_container_manager import AsyncDockerContainerManager


def get_docker_endpoints():
    """Get Docker endpoints from environment or provide example."""
    endpoints_env = os.environ.get("DOCKER_ENDPOINTS", "")
    if endpoints_env:
        endpoints = [ep.strip() for ep in endpoints_env.split(",")]
        print(f"Using multi-node Docker setup with {len(endpoints)} nodes:")
        for i, ep in enumerate(endpoints):
            print(f"  Node {i}: {ep}")
        return endpoints
    else:
        print("ERROR: DOCKER_ENDPOINTS environment variable not set!")
        print("Example: export DOCKER_ENDPOINTS='unix:///var/run/docker.sock,tcp://10.15.25.9:2375'")
        return None


async def test_multi_node_load_balancing():
    """Test that containers are distributed across multiple nodes."""

    endpoints = get_docker_endpoints()
    if not endpoints:
        return

    if len(endpoints) < 2:
        print("WARNING: Need at least 2 Docker endpoints to test multi-node functionality")
        return

    # Create a temporary directory for our test Dockerfile
    temp_dir = tempfile.mkdtemp(prefix="docker_test_multinode_")

    try:
        # Create a simple Dockerfile
        dockerfile_content = """
FROM python:3.9-slim

RUN echo "Multi-node test image"

CMD ["python", "-c", "print('Hello from multi-node test')"]
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        print(f"Created test Dockerfile in: {temp_dir}")

        # Test the AsyncDockerContainerManager with multi-node setup
        async with AsyncDockerContainerManager(docker_endpoints=endpoints) as manager:
            print(f"\nInitialized manager with {len(manager.clients)} nodes")
            print(f"Initial active container counts: {manager.active_container_counts}")

            # Create multiple containers and verify load balancing
            num_containers = 6
            container_ids = []

            print(f"\nCreating {num_containers} containers...")
            for i in range(num_containers):
                container_id = await manager.spin_up_container_from_dir(
                    build_context_dir=temp_dir,
                    image_name=f"test-multinode-{i}"
                )
                container_ids.append(container_id)

                # Get the node this container was placed on
                node_idx, _ = manager.containers[container_id]
                print(f"Container {i+1}: {container_id[:12]} -> Node {node_idx}")
                print(f"  Active containers per node: {manager.active_container_counts}")

            # Verify distribution
            print(f"\nFinal distribution: {manager.active_container_counts}")

            # Verify load balancing worked (counts should be relatively even)
            max_count = max(manager.active_container_counts)
            min_count = min(manager.active_container_counts)
            print(f"Load balance: max={max_count}, min={min_count}, diff={max_count - min_count}")

            if max_count - min_count <= 1:
                print("✓ Load balancing is working correctly!")
            else:
                print("✗ Load balancing may not be working as expected")

            # Test executing commands on containers on different nodes
            print("\nTesting command execution across nodes...")
            for i, container_id in enumerate(container_ids[:2]):  # Test first 2 containers
                node_idx, _ = manager.containers[container_id]
                stdout, stderr = await manager.execute_command(
                    container_id=container_id,
                    command=f"echo 'Hello from container {i+1} on node {node_idx}'"
                )
                print(f"Container {i+1} (Node {node_idx}): {stdout.strip()}")

            # Clean up all containers concurrently
            print("\nCleaning up containers...")
            await asyncio.gather(*[manager.close_container(cid) for cid in container_ids])

            print(f"Final active container counts: {manager.active_container_counts}")
            print("✓ All containers cleaned up successfully")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def test_multi_node_file_operations():
    """Test file copy operations across multiple nodes."""

    endpoints = get_docker_endpoints()
    if not endpoints or len(endpoints) < 2:
        return

    temp_dir = tempfile.mkdtemp(prefix="docker_test_files_")

    try:
        # Create Dockerfile
        dockerfile_content = """
FROM python:3.9-slim
RUN mkdir -p /app
WORKDIR /app
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        # Create a test file to copy
        test_file_path = os.path.join(temp_dir, "test.txt")
        test_content = "Multi-node file copy test"
        with open(test_file_path, 'w') as f:
            f.write(test_content)

        print(f"Created test files in: {temp_dir}")

        async with AsyncDockerContainerManager(docker_endpoints=endpoints) as manager:
            # Create containers on different nodes
            container_ids = []
            for i in range(min(4, len(endpoints) * 2)):
                container_id = await manager.spin_up_container_from_dir(
                    build_context_dir=temp_dir,
                    image_name=f"test-file-ops-{i}"
                )
                container_ids.append(container_id)
                node_idx, _ = manager.containers[container_id]
                print(f"Created container {container_id[:12]} on node {node_idx}")

            # Copy files to each container and verify
            print("\nTesting file copy operations...")
            for i, container_id in enumerate(container_ids):
                node_idx, _ = manager.containers[container_id]

                await manager.copy_file_to_container(
                    container_id=container_id,
                    local_file_path=test_file_path,
                    container_file_path=f"/app/copied_{i}.txt"
                )

                stdout, stderr = await manager.execute_command(
                    container_id=container_id,
                    command=f"cat /app/copied_{i}.txt"
                )

                if stdout.strip() == test_content:
                    print(f"✓ Container {i+1} (Node {node_idx}): File copied successfully")
                else:
                    print(f"✗ Container {i+1} (Node {node_idx}): File copy failed")

            # Cleanup concurrently
            await asyncio.gather(*[manager.close_container(cid) for cid in container_ids])

            print("\n✓ File operations test completed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def test_multi_node_concurrent_builds():
    """Test that multiple containers can be built concurrently on different nodes."""

    endpoints = get_docker_endpoints()
    if not endpoints or len(endpoints) < 2:
        return

    temp_dir = tempfile.mkdtemp(prefix="docker_test_concurrent_")

    try:
        # Create Dockerfile
        dockerfile_content = """
FROM python:3.9-slim
RUN echo "Concurrent build test"
RUN sleep 1
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        print(f"Created test Dockerfile in: {temp_dir}")

        async with AsyncDockerContainerManager(docker_endpoints=endpoints) as manager:
            print("\nTesting concurrent container creation...")

            # Create multiple containers concurrently
            num_containers = len(endpoints) * 2

            async def create_container(index):
                container_id = await manager.spin_up_container_from_dir(
                    build_context_dir=temp_dir,
                    image_name=f"test-concurrent-{index}"
                )
                node_idx, _ = manager.containers[container_id]
                return container_id, node_idx

            import time
            start_time = time.time()

            # Create containers concurrently
            results = await asyncio.gather(
                *[create_container(i) for i in range(num_containers)]
            )

            elapsed = time.time() - start_time

            print(f"\nCreated {num_containers} containers in {elapsed:.2f}s")
            for i, (container_id, node_idx) in enumerate(results):
                print(f"  Container {i+1}: {container_id[:12]} on Node {node_idx}")

            print(f"\nFinal distribution: {manager.active_container_counts}")

            # Cleanup
            cleanup_tasks = [manager.close_container(cid) for cid, _ in results]
            await asyncio.gather(*cleanup_tasks)

            print("✓ Concurrent build test completed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def main():
    """Run all multi-node tests."""
    print("=" * 60)
    print("Multi-Node Docker Manager Tests")
    print("=" * 60)

    endpoints = get_docker_endpoints()
    if not endpoints:
        print("\nPlease set DOCKER_ENDPOINTS environment variable to run multi-node tests.")
        print("Example:")
        print("  export DOCKER_ENDPOINTS='unix:///var/run/docker.sock,tcp://10.15.25.9:2375'")
        return

    if len(endpoints) < 2:
        print(f"\nWARNING: Only {len(endpoints)} endpoint(s) configured.")
        print("Multi-node tests require at least 2 Docker endpoints.")
        return

    print("\n" + "=" * 60)
    print("Test 1: Multi-node load balancing")
    print("=" * 60)
    await test_multi_node_load_balancing()

    print("\n" + "=" * 60)
    print("Test 2: File operations across nodes")
    print("=" * 60)
    await test_multi_node_file_operations()

    print("\n" + "=" * 60)
    print("Test 3: Concurrent builds across nodes")
    print("=" * 60)
    await test_multi_node_concurrent_builds()

    print("\n" + "=" * 60)
    print("All multi-node tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
