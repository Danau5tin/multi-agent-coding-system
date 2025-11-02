#!/usr/bin/env python3
import asyncio
import os
import sys

from multi_agent_coding_system.misc.async_docker_container_manager import AsyncDockerContainerManager

# Add parent directory to path to enable src imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import uuid
import tempfile
import shutil

from multi_agent_coding_system.agents.env_interaction.command_executor import DockerExecutor
from multi_agent_coding_system.agents.orchestrator_agent import OrchestratorAgent
from pathlib import Path


async def test_orchestator_simple_task(
    instruction: str, run_id: str, temperature=0.1, logging_dir=None
):
    """Test orchestrator with a simple task.

    Args:
        instruction: The task instruction to execute
        temperature: LLM temperature setting
        logging_dir: Optional directory for turn-by-turn logging
    """
    # Generate unique container name
    container_name = f"test_orchestrator_{run_id}"

    # Set up logging directory if requested
    if logging_dir:
        logging_path = Path(logging_dir)
        logging_path.mkdir(exist_ok=True, parents=True)
        print(f"Logging turns to: {logging_path}")
    else:
        logging_path = None

    # Create temporary directory for Dockerfile
    temp_dir = tempfile.mkdtemp(prefix="test_orchestrator_")
    dockerfile_content = """FROM ubuntu:latest
RUN apt-get update && apt-get install -y bash
WORKDIR /workspace
CMD ["/bin/bash"]
"""

    # Initialize the Docker manager
    manager = AsyncDockerContainerManager()
    container_id = None

    try:
        # Write Dockerfile to temp directory
        dockerfile_path = Path(temp_dir) / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)

        # Start Docker container using the manager
        print(f"Starting Docker container with image: {container_name}")
        await manager._ensure_initialized()
        container_id = await manager.spin_up_container_from_dir(
            build_context_dir=temp_dir,
            image_name=container_name
        )
        print(f"Container started with ID: {container_id}")

        # Wait a moment for container to stabilize
        await asyncio.sleep(1)

        # Use container ID instead of name for DockerExecutor
        # Note: DockerExecutor expects container name, but we can use ID
        executor = DockerExecutor(container_id)

        orchestrator = OrchestratorAgent(
            temperature=temperature,
        )
        orchestrator.setup(executor, logging_dir=logging_path, session_id=run_id)

        print("\nExecuting task...")
        result = await orchestrator.run(instruction, max_turns=15)

        # Display results
        print(f"\n{'=' * 40}")
        print("EXECUTION RESULT:")
        print(f"{'=' * 40}")
        print(f"Completed: {result['completed']}")
        print(f"Finish message: {result['finish_message']}")
        print(f"Turns executed: {result['turns_executed']}")
        print(f"Max turns reached: {result['max_turns_reached']}")

        # Check if files were created in container
        print(f"\n{'=' * 40}")
        print("VERIFICATION:")
        print(f"{'=' * 40}")

        # Check 5 txt files exist using the manager's execute_command
        stdout, stderr = await manager.execute_command(
            container_id=container_id,
            command="cd /workspace && ls *.txt 2>/dev/null | wc -l"
        )
        num_text_files = stdout.strip() if stdout else "0"

        if num_text_files and int(num_text_files) >= 5:
            print(f"✓ Found {num_text_files} .txt files in /workspace")
        else:
            print(f"✗ Expected 5 .txt files, but found {num_text_files}")
            stdout, stderr = await manager.execute_command(
                container_id=container_id,
                command="cd /workspace && ls -l"
            )
            print("  - Listing files in /workspace:")
            print(stdout)

        return result

    finally:
        # Clean up Docker container and temporary directory
        try:
            if container_id:
                print(f"\nStopping and removing container: {container_id}")
                await manager.close_container(container_id)
            await manager.close()
        except Exception as e:
            print(f"Error cleaning up container: {e}")

        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Error cleaning up temp directory: {e}")


async def main():
    """Main test runner."""

    os.environ["LITE_LLM_API_KEY"] = ""  # TODO: Set this

    os.environ["ORCA_ORCHESTRATOR_MODEL"] = (
        "openrouter/qwen/qwen3-14b"
        # "openrouter/qwen/qwen3-30b-a3b"
        # "openrouter/openai/gpt-5"
        # "openrouter/nvidia/nemotron-nano-9b-v2"
        # "openrouter/qwen/qwen3-8b"
        # "openrouter/microsoft/phi-4-reasoning-plus"
        # "openrouter/meta-llama/llama-3.3-8b-instruct"
        # "openrouter/mistralai/devstral-small"
        # "openrouter/microsoft/phi-4"
        # "openrouter/nvidia/nemotron-nano-9b-v2"
        # "openrouter/arcee-ai/afm-4.5b"
        # "openrouter/qwen/qwen3-30b-a3b-instruct-2507"
        # "openrouter/qwen/qwen3-next-80b-a3b-instruct"
        # "openrouter/qwen/qwen3-coder"
        # "openrouter/qwen/qwen3-coder-30b-a3b-instruct"
        # "openrouter/qwen/qwen3-32b"
    )
    os.environ["ORCA_SUBAGENT_MODEL"] = (
        "openrouter/qwen/qwen3-coder-30b-a3b-instruct"
        # "openrouter/nvidia/nemotron-nano-9b-v2"
        # "openrouter/openai/gpt-5"
        # "openrouter/x-ai/grok-code-fast-1"
        # "openrouter/qwen/qwen3-coder"
        # "openrouter/qwen/qwen3-32b"
        # "openrouter/qwen/qwen3-next-80b-a3b-instruct"
    )
    instruction = (
        "Create 5 txt files, each with a poem about a different programming language."
    )
    time_stamp_dd_mm_hh_mm = time.strftime("%d_%H%M", time.localtime())
    run_id = time_stamp_dd_mm_hh_mm + uuid.uuid4().hex[:8]

    logging_dir = f"./session_logs/"

    result = await test_orchestator_simple_task(
        instruction=instruction, run_id=run_id, temperature=0.7, logging_dir=logging_dir
    )
    print(f"\nFinal result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
