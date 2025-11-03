"""Action definitions using Pydantic for automatic YAML validation."""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class Action(BaseModel):
    """Base action class using Pydantic for validation."""
    
    class Config:
        extra = "forbid"  # Reject unknown fields
        validate_assignment = True


class BashAction(Action):
    """Execute a bash command."""
    cmd: str = Field(..., min_length=1, description="Command to execute")
    block: bool = Field(True, description="Wait for command to complete")
    timeout_secs: int = Field(1, gt=0, le=300, description="Timeout in seconds")


class FinishAction(Action):
    """Mark task as finished."""
    message: str = Field("Task completed", description="Completion message")


# Todo Actions
class TodoOperation(BaseModel):
    """Single todo operation."""
    action: Literal["add", "complete", "delete", "view_all"]
    content: Optional[str] = None
    task_id: Optional[int] = None
    
    @field_validator('content')
    @classmethod
    def validate_content(cls, v, info):
        if info.data.get('action') == 'add' and not v:
            raise ValueError("'add' action requires 'content'")
        return v
    
    @field_validator('task_id')
    @classmethod
    def validate_task_id(cls, v, info):
        action = info.data.get('action')
        if action in ['complete', 'delete']:
            if v is None or v < 1:
                raise ValueError(f"'{action}' action requires positive task_id")
        return v


class BatchTodoAction(Action):
    """Batch todo operations."""
    operations: List[TodoOperation] = Field(..., min_length=1)
    view_all: bool = Field(False)


# File Actions
class ReadAction(Action):
    """Read a file."""
    file_path: str = Field(..., min_length=1)
    offset: Optional[int] = Field(None, ge=0)
    limit: Optional[int] = Field(None, gt=0)


class WriteAction(Action):
    """Write to a file."""
    file_path: str = Field(..., min_length=1)
    content: str = Field(...)


class EditAction(Action):
    """Edit a file."""
    file_path: str = Field(..., min_length=1)
    old_string: str = Field(...)
    new_string: str = Field(...)
    replace_all: bool = Field(False)


class EditOperation(BaseModel):
    """Single edit operation for multi-edit."""
    old_string: str
    new_string: str
    replace_all: bool = False


class MultiEditAction(Action):
    """Multiple edits to a single file."""
    file_path: str = Field(..., min_length=1)
    edits: List[EditOperation] = Field(..., min_length=1)


class FileMetadataAction(Action):
    """Get metadata for files."""
    file_paths: List[str] = Field(..., min_length=1, max_length=10)


# Search Actions
class GrepAction(Action):
    """Search file contents with regex."""
    pattern: str = Field(..., min_length=1)
    path: Optional[str] = None
    include: Optional[str] = None


class GlobAction(Action):
    """Find files matching glob pattern."""
    pattern: str = Field(..., min_length=1)
    path: Optional[str] = None


# Scratchpad Actions
class AddNoteAction(Action):
    """Add a note to scratchpad."""
    content: str = Field(..., min_length=1)


class ViewAllNotesAction(Action):
    """View all notes in scratchpad."""
    pass  # No fields needed


# Task Management Actions
class TaskSpec(BaseModel):
    """Base task specification shared by single and parallel task creation."""
    agent_type: Literal["explorer", "coder"]
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    max_turns: int = Field(8, gt=0, le=20)
    context_refs: List[str] = Field(default_factory=list)
    context_bootstrap: List[dict] = Field(default_factory=list)
    
    @field_validator('context_bootstrap')
    @classmethod
    def validate_bootstrap(cls, v):
        for i, item in enumerate(v):
            if not isinstance(item, dict):
                raise ValueError(f"context_bootstrap[{i}] must be a dict")
            if 'path' not in item or 'reason' not in item:
                raise ValueError(f"context_bootstrap[{i}] needs 'path' and 'reason'")
        return v

class TaskCreateAction(TaskSpec, Action):
    """Create a new task."""
    auto_launch: bool = Field(True)


class AddContextAction(Action):
    """Add context to store."""
    id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    reported_by: str = Field("?")
    task_id: Optional[str] = None


class LaunchSubagentAction(Action):
    """Launch a subagent task."""
    task_id: str = Field(..., min_length=1)


class LaunchParallelSubAgentsAction(Action):
    """Launch multiple subagents agents in parallel."""
    tasks: List[TaskSpec] = Field(..., min_length=1, max_length=10)


class ReportAction(Action):
    """Report task results."""
    contexts: List[dict] = Field(default_factory=list)
    context_refs: List[str] = Field(default_factory=list)  # References to existing contexts
    comments: str = Field("")


class WriteTempScriptAction(Action):
    """Write a temporary script file."""
    file_path: str = Field(..., min_length=1)
    content: str = Field(...)


# Example usage showing how clean this is:
if __name__ == "__main__":
    import yaml
    
    # Test bash action
    yaml_str = """
    cmd: "ls -la"
    timeout_secs: 60
    """
    data = yaml.safe_load(yaml_str)
    action = BashAction.model_validate(data)
    print(f"Created: {action}")