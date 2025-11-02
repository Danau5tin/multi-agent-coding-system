"""Search manager for handling search operations in the Docker container."""

import logging
from typing import List, Optional, Tuple

from multi_agent_coding_system.agents.env_interaction.command_executor import CommandExecutor


logger = logging.getLogger(__name__)


class SearchManager:
    """Manages search operations within Docker container."""
    
    def __init__(self, executor: CommandExecutor):
        self.executor = executor
    
    async def _run_command(self, cmd: str, timeout: int = 30) -> Tuple[str, int]:
        """Run a command using the executor and return (output, exit_code)."""
        return await self.executor.execute(cmd, timeout=timeout)
    
    async def grep(self, pattern: str, path: Optional[str] = None,
                  include: Optional[str] = None) -> Tuple[str, bool]:
        """Search file contents using grep with regex patterns."""
        # Build grep command with appropriate flags
        grep_flags = [
            '-r',  # Recursive
            '-n',  # Show line numbers
            '-H',  # Show filenames
            '--color=never'  # Disable color output
        ]
        
        # Add include pattern if specified
        if include:
            grep_flags.append(f"--include='{include}'")
        
        # Use current directory if no path specified
        search_path = path or '.'
        
        # Escape single quotes in pattern
        escaped_pattern = pattern.replace("'", "'\"'\"'")
        
        # Build command
        cmd = f"grep {' '.join(grep_flags)} '{escaped_pattern}' '{search_path}' 2>/dev/null | head -n 100"

        output, code = await self._run_command(cmd)
        
        # Grep returns 1 when no matches found, which is not an error
        if code == 1 and not output:
            return "No matches found", False
        elif code > 1:
            return f"Error during search: {output}", True
        
        # Format output
        lines = output.strip().split('\n') if output.strip() else []
        if len(lines) == 100:
            result = '\n'.join(lines) + "\n\n[Output truncated to 100 matches]"
        else:
            result = output if output else "No matches found"
        
        return result, False
    
    async def glob(self, pattern: str, path: Optional[str] = None) -> Tuple[str, bool]:
        """Find files by name pattern using find command."""
        # Use current directory if no path specified
        search_path = path or '.'
        
        # Convert glob pattern to find pattern
        # Basic conversion - more sophisticated conversion could be added
        find_pattern = pattern.replace('**/', '*/').replace('*', '*')
        
        # Build find command
        cmd = f"find '{search_path}' -name '{find_pattern}' -type f 2>/dev/null | head -n 100 | sort"

        output, code = await self._run_command(cmd)
        
        if code != 0:
            return f"Error during file search: {output}", True
        
        # Format output
        lines = output.strip().split('\n') if output.strip() else []
        if not lines or (len(lines) == 1 and not lines[0]):
            return "No files found matching pattern", False
        
        if len(lines) == 100:
            result = '\n'.join(lines) + "\n\n[Output truncated to 100 files]"
        else:
            result = '\n'.join(lines)
        
        return result, False
    
    async def ls(self, path: str, ignore: Optional[List[str]] = None) -> Tuple[str, bool]:
        """List directory contents."""
        # Check if path exists and is a directory
        check_cmd = f"test -d '{path}' && echo 'dir' || (test -e '{path}' && echo 'not_dir' || echo 'not_found')"
        output, _ = await self._run_command(check_cmd)
        
        if "not_found" in output:
            return f"Path not found: {path}", True
        elif "not_dir" in output:
            return f"Path is not a directory: {path}", True
        
        # Build ls command with detailed output
        ls_cmd = f"ls -la '{path}' 2>/dev/null"
        
        output, code = await self._run_command(ls_cmd)
        
        if code != 0:
            return f"Error listing directory: {output}", True
        
        # Filter out ignored patterns if specified
        if ignore and output:
            lines = output.strip().split('\n')
            filtered_lines = []
            
            for line in lines:
                # Skip the total line and empty lines
                if line.startswith('total') or not line.strip():
                    filtered_lines.append(line)
                    continue
                
                # Extract filename from ls output (last field)
                parts = line.split()
                if len(parts) >= 9:
                    filename = ' '.join(parts[8:])
                    
                    # Check if filename matches any ignore pattern
                    should_ignore = False
                    for pattern in ignore:
                        # Simple pattern matching (could be enhanced)
                        if pattern.startswith('*') and filename.endswith(pattern[1:]):
                            should_ignore = True
                            break
                        elif pattern.endswith('*') and filename.startswith(pattern[:-1]):
                            should_ignore = True
                            break
                        elif pattern in filename:
                            should_ignore = True
                            break
                    
                    if not should_ignore:
                        filtered_lines.append(line)
                else:
                    filtered_lines.append(line)
            
            output = '\n'.join(filtered_lines)
        
        return output, False