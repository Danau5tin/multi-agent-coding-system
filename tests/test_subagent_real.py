#!/usr/bin/env python3
import asyncio
import os

from multi_agent_coding_system.misc.async_docker_container_manager import (
    AsyncDockerContainerManager,
)

import time
import uuid
import tempfile
import shutil

from multi_agent_coding_system.agents.env_interaction.command_executor import (
    DockerExecutor,
)
from multi_agent_coding_system.agents.subagent import Subagent, SubagentTask
from multi_agent_coding_system.agents.actions.orchestrator_hub import OrchestratorHub
from multi_agent_coding_system.agents.actions.hierarchical_task_manager import (
    HierarchicalTaskManager,
)
from multi_agent_coding_system.misc.session_logger import (
    SessionLogger,
    SubagentSessionTracker,
    AgentType,
)
from pathlib import Path

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_subagent_simple_task(
    instruction: str, run_id: str, temperature=0.1, logging_dir=None
):
    """Test subagent with a simple task.

    Args:
        instruction: The task instruction to execute
        temperature: LLM temperature setting
        logging_dir: Optional directory for turn-by-turn logging
    """
    # Generate unique container name
    container_name = f"test_subagent_{run_id}"

    # Set up logging directory if requested
    if logging_dir:
        logging_path = Path(logging_dir)
        logging_path.mkdir(exist_ok=True, parents=True)
        print(f"Logging turns to: {logging_path}")
    else:
        logging_path = None

    # Initialize SessionLogger
    session_logger = SessionLogger(
        logging_dir=logging_path, session_id=run_id, agent_type=AgentType.SUBAGENT
    )
    await session_logger.start_session(
        task=instruction,
        metadata={"temperature": temperature, "container_name": container_name},
    )

    # Create temporary directory for Dockerfile
    temp_dir = tempfile.mkdtemp(prefix="test_subagent_")
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
            build_context_dir=temp_dir, image_name=container_name
        )
        print(f"Container started with ID: {container_id}")

        # Use container ID for DockerExecutor
        executor = DockerExecutor(container_id)

        # Initial check for files (this was in original code)
        num_text_files_str, _ = await executor.execute(
            cmd="ls *.txt 2>/dev/null | wc -l", timeout=5
        )

        # Wait a moment for container to stabilize
        await asyncio.sleep(1)

        # Create orchestrator hub for context management
        task_manager = HierarchicalTaskManager()
        orchestrator_hub = OrchestratorHub(
            agent_id="test_orchestrator", task_manager=task_manager
        )

        # Create SubagentTask
        task = SubagentTask(
            agent_type="coder",
            title="Execute instruction",
            description=instruction,
            max_turns=15,
            ctx_store_ctxts={},
            bootstrap_ctxts=[],
        )

        # Create subagent
        agent_id = f"test_sub_{uuid.uuid4().hex[:8]}"

        # Create SubagentSessionTracker
        subagent_tracker = SubagentSessionTracker(
            parent_logger=session_logger,
            agent_id=agent_id,
            agent_type="coder",
            task_title="Execute instruction",
            task_description=instruction,
            max_turns=15,
        )

        subagent = Subagent(
            agent_id=agent_id,
            task=task,
            executor=executor,
            orchestrator_hub=orchestrator_hub,
            temperature=temperature,
            session_tracker=subagent_tracker,
            logging_dir=logging_path,
        )

        print("\nExecuting task...")
        report = await subagent.run()

        # Display results
        print(f"\n{'=' * 40}")
        print("EXECUTION RESULT:")
        print(f"{'=' * 40}")
        print(f"Comments: {report.comments}")
        print(f"\nContexts ({len(report.contexts)}):")
        for ctx in report.contexts:
            print(
                f"  - {ctx.id}: {ctx.content[:100]}..."
                if len(ctx.content) > 100
                else f"  - {ctx.id}: {ctx.content}"
            )

        # Show trajectory summary
        turns_executed = 0
        if report.meta and report.meta.trajectory:
            # Subtract system and initial user message
            turns_executed = (len(report.meta.trajectory) - 2) // 2
            print(f"Turns executed: {turns_executed}")

        # Check if files were created in container
        print(f"\n{'=' * 40}")
        print("VERIFICATION:")
        print(f"{'=' * 40}")

        # Check 5 txt files exist using the manager's execute_command
        stdout, stderr = await manager.execute_command(
            container_id=container_id,
            command="cd /workspace && ls *.txt 2>/dev/null | wc -l",
        )
        num_text_files = stdout.strip() if stdout else "0"

        if num_text_files and int(num_text_files) >= 5:
            print(f"✓ Found {num_text_files} .txt files in /workspace")
        else:
            print(f"✗ Expected 5 .txt files, but found {num_text_files}")
            stdout, stderr = await manager.execute_command(
                container_id=container_id, command="cd /workspace && ls -l"
            )
            print("  - Listing files in /workspace:")
            print(stdout)

        # Finish subagent tracking
        await subagent_tracker.finish(report=report.to_dict())

        # End session
        await session_logger.end_session(
            reason="completed" if report and report.comments else "failed"
        )

        return report

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

    os.environ["ORCA_SUBAGENT_MODEL"] = (
        "openrouter/qwen/qwen3-coder-30b-a3b-instruct"
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

    logging_dir = f"logs/test_subagent/{run_id}/"

    await test_subagent_simple_task(
        instruction=instruction, run_id=run_id, temperature=0.1, logging_dir=logging_dir
    )


if __name__ == "__main__":
    asyncio.run(main())
