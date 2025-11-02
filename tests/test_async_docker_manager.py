import asyncio
import tempfile
import os
import shutil

from multi_agent_coding_system.misc.async_docker_container_manager import AsyncDockerContainerManager


async def test_build_and_run_container():
    """Test building an image and running a container from a Dockerfile."""

    # Create a temporary directory for our test Dockerfile
    temp_dir = tempfile.mkdtemp(prefix="docker_test_")

    try:
        # Create a simple Dockerfile
        dockerfile_content = """
FROM python:3.9-slim

RUN echo "Test image built successfully"

CMD ["python", "-c", "print('Hello from test container')"]
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        print(f"Created test Dockerfile in: {temp_dir}")

        # Test the AsyncDockerContainerManager
        async with AsyncDockerContainerManager() as manager:
            print("Building and starting container...")

            # Build and run the container
            container_id = await manager.spin_up_container_from_dir(
                build_context_dir=temp_dir,
                image_name="test-async-docker-manager"
            )

            print(f"Container started with ID: {container_id}")

            # Execute a test command
            stdout, stderr = await manager.execute_command(
                container_id=container_id,
                command="echo 'Container is running!' && python -c 'print(\"Python is working\")'"
            )

            print(f"Command output:\n{stdout}")
            if stderr:
                print(f"Command stderr:\n{stderr}")

            # Test file copy
            test_file_path = os.path.join(temp_dir, "test.txt")
            with open(test_file_path, 'w') as f:
                f.write("This is a test file")

            await manager.copy_file_to_container(
                container_id=container_id,
                local_file_path=test_file_path,
                container_file_path="/tmp/test.txt"
            )

            stdout, stderr = await manager.execute_command(
                container_id=container_id,
                command="cat /tmp/test.txt"
            )

            print(f"File content in container: {stdout}")

            # Clean up the container
            print("Cleaning up container...")
            await manager.close_container(container_id)
            print("Container cleaned up successfully")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def test_build_failure():
    """Test that build failures are properly reported with logs."""

    temp_dir = tempfile.mkdtemp(prefix="docker_test_fail_")

    try:
        # Create a Dockerfile that will fail
        dockerfile_content = """
FROM python:3.9-slim

# This will cause a build failure
RUN exit 1
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        print(f"Created failing Dockerfile in: {temp_dir}")

        async with AsyncDockerContainerManager() as manager:
            try:
                container_id = await manager.spin_up_container_from_dir(
                    build_context_dir=temp_dir,
                    image_name="test-failing-build"
                )
                print("ERROR: Build should have failed but didn't!")
            except Exception as e:
                print(f"Build failed as expected: {e}")
                print("Build logs should appear above this line")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def test_dockerfile_copy():
    """Test that Dockerfile can copy files from build context during build."""

    temp_dir = tempfile.mkdtemp(prefix="docker_test_copy_")

    try:
        # Create a test file in the build context
        test_content = "This file was copied during Docker build!"
        test_file_path = os.path.join(temp_dir, "build_test.txt")
        with open(test_file_path, 'w') as f:
            f.write(test_content)

        # Create Dockerfile that copies the file during build
        dockerfile_content = """
FROM python:3.9-slim

# Copy the test file from build context
COPY build_test.txt /app/copied_during_build.txt

# Verify the file was copied
RUN cat /app/copied_during_build.txt

CMD ["python", "-c", "import os; print(f'Files in /app: {os.listdir(\"/app\")}')"]
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        print(f"Created test files in: {temp_dir}")
        print(f"  - Dockerfile")
        print(f"  - build_test.txt (to be copied during build)")

        async with AsyncDockerContainerManager() as manager:
            print("Building and starting container...")

            # Build and run the container
            container_id = await manager.spin_up_container_from_dir(
                build_context_dir=temp_dir,
                image_name="test-dockerfile-copy"
            )

            print(f"Container started with ID: {container_id}")

            # Check if the file exists in the container
            stdout, stderr = await manager.execute_command(
                container_id=container_id,
                command="ls -la /app/"
            )
            print(f"Files in /app/:\n{stdout}")

            # Read the content of the copied file
            stdout, stderr = await manager.execute_command(
                container_id=container_id,
                command="cat /app/copied_during_build.txt"
            )
            print(f"Content of copied file: {stdout}")

            # Verify content matches
            if stdout.strip() == test_content:
                print("✓ File was successfully copied during build with correct content!")
            else:
                print(f"✗ File content mismatch. Expected: '{test_content}', Got: '{stdout.strip()}'")

            # Clean up the container
            print("Cleaning up container...")
            await manager.close_container(container_id)
            print("Container cleaned up successfully")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def test_command_timeout():
    """Test that command execution respects timeout parameter."""

    temp_dir = tempfile.mkdtemp(prefix="docker_test_timeout_")

    try:
        # Create a simple Dockerfile
        dockerfile_content = """
FROM python:3.9-slim

CMD ["/bin/bash"]
"""
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        print(f"Created test Dockerfile in: {temp_dir}")

        async with AsyncDockerContainerManager() as manager:
            print("Building and starting container...")

            container_id = await manager.spin_up_container_from_dir(
                build_context_dir=temp_dir,
                image_name="test-timeout"
            )

            print(f"Container started with ID: {container_id}")

            # Test 1: Command that completes within timeout
            print("\nTest 1: Command that completes within timeout (5 seconds)...")
            try:
                stdout, stderr = await manager.execute_command(
                    container_id=container_id,
                    command="echo 'Quick command' && sleep 1",
                    timeout=5
                )
                print(f"✓ Command completed successfully: {stdout.strip()}")
            except Exception as e:
                print(f"✗ Unexpected error: {e}")

            # Test 2: Command that exceeds timeout
            print("\nTest 2: Command that exceeds timeout (2 seconds)...")
            try:
                stdout, stderr = await manager.execute_command(
                    container_id=container_id,
                    command="echo 'Starting long command...' && sleep 10",
                    timeout=2
                )
                print(f"✗ Command should have timed out but didn't! Output: {stdout}")
            except asyncio.TimeoutError:
                print("✓ Command timed out as expected (asyncio.TimeoutError)")
            except Exception as e:
                print(f"✓ Command timed out with exception: {type(e).__name__}: {e}")

            # Test 3: Command without timeout (should use default behavior)
            print("\nTest 3: Command without explicit timeout...")
            try:
                stdout, stderr = await manager.execute_command(
                    container_id=container_id,
                    command="echo 'No timeout specified' && sleep 1"
                )
                print(f"✓ Command completed: {stdout.strip()}")
            except Exception as e:
                print(f"✗ Unexpected error: {e}")

            # Clean up
            print("\nCleaning up container...")
            await manager.close_container(container_id)
            print("Container cleaned up successfully")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def test_build_dockerfile_with_heredoc_syntax():
    """Test building an image and running a simple ls command."""

    temp_dir = tempfile.mkdtemp(prefix="docker_test_simple_")

    try:
        # Copy the Dockerfile from test_assets
        test_assets_dir = os.path.join(
            os.path.dirname(__file__),
            "test_assets"
        )
        source_dockerfile = os.path.join(test_assets_dir, "dockerfile_with_heredoc")
        dest_dockerfile = os.path.join(temp_dir, "Dockerfile")

        shutil.copy(source_dockerfile, dest_dockerfile)

        print(f"Created test Dockerfile in: {temp_dir}")

        async with AsyncDockerContainerManager() as manager:
            print("Building and starting container...")

            # Build and run the container
            container_id = await manager.spin_up_container_from_dir(
                build_context_dir=temp_dir,
                image_name="test-simple-ls"
            )

            print(f"Container started with ID: {container_id}")

            # Execute ls command
            stdout, stderr = await manager.execute_command(
                container_id=container_id,
                command="ls -la /"
            )

            print(f"ls command output:\n{stdout}")

            # Assert test pass
            assert stdout, "ls command should produce output"
            assert "bin" in stdout or "usr" in stdout, "Expected standard directories not found"
            print("✓ Test passed: Container built successfully and ls command executed")

            # Clean up the container
            print("Cleaning up container...")
            await manager.close_container(container_id)
            print("Container cleaned up successfully")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Test 1: Build and run container")
    print("=" * 60)
    await test_build_and_run_container()

    print("\n" + "=" * 60)
    print("Test 2: Build failure with logs")
    print("=" * 60)
    await test_build_failure()

    print("\n" + "=" * 60)
    print("Test 3: Dockerfile COPY instruction")
    print("=" * 60)
    await test_dockerfile_copy()

    print("\n" + "=" * 60)
    print("Test 4: Command timeout")
    print("=" * 60)
    await test_command_timeout()

    print("\n" + "=" * 60)
    print("Test 5: Build Dockerfile with heredoc syntax")
    print("=" * 60)
    await test_build_dockerfile_with_heredoc_syntax()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())