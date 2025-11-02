"""Initial environment setup module for running startup commands and formatting output."""

from multi_agent_coding_system.agents.env_interaction.command_executor import CommandExecutor


class EnvInfoRetriever:
    """Handles running initial environment commands and formatting their output."""

    # Static list of commands to run on startup
    STARTUP_COMMANDS = [
        "pwd",
        "python --version && pip --version && pip list",
        "find . -type f | sed 's/.*\\.//' | sort | uniq -c | sort -rn | head -10",
        "find . -maxdepth 3 -type f | head -30",
        "find . -type f \\( -iname \"*readme*\" -o -iname \"*task*\" -o -iname \"*todo*\" -o -iname \"*instruction*\" \\) 2>/dev/null",
        "head -n 20 requirements.txt package.json Makefile Dockerfile .env pyproject.toml 2>/dev/null",
        "ps | head -5",
        "df -h",
        "env"
    ]

    def __init__(self, command_executor: CommandExecutor):
        self.command_executor = command_executor

    async def run_and_format(self, title: str) -> str:
        """
        Run all startup commands and format the output.

        Returns:
            A formatted string containing all command outputs
        """
        results = []
        results.append(f"## {title}\n")

        for cmd in self.STARTUP_COMMANDS:
            try:
                output, _ = await self.command_executor.execute(cmd, timeout=5)

                # Format the command and output
                results.append(f"\ncmd: `{cmd}`")
                results.append("output:")
                results.append("```")
                results.append(output.rstrip())
                results.append("```")
                results.append("\n")
            except:
                # Ignore failures, just skip this command
                pass

        return "\n".join(results)