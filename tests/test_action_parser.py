#!/usr/bin/env python3
"""Comprehensive test suite for action parser and integration."""

import asyncio
import pytest
from multi_agent_coding_system.agents.actions.parsing.parser import SimpleActionParser
from multi_agent_coding_system.agents.actions.entities.actions import (
    BashAction, FinishAction, BatchTodoAction,
    ReadAction, WriteAction, EditAction, MultiEditAction, FileMetadataAction,
    GrepAction, GlobAction,
    AddNoteAction, ViewAllNotesAction,
    TaskCreateAction, AddContextAction, LaunchSubagentAction, ReportAction,
    WriteTempScriptAction
)
from multi_agent_coding_system.agents.actions.parsing.action_handler import ActionHandler
from multi_agent_coding_system.agents.env_interaction.turn_executor import TurnExecutor
from multi_agent_coding_system.agents.actions.state_managers import TodoManager, ScratchpadManager


class TestActionParser:
    """Test suite for action parser functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.parser = SimpleActionParser()
    
    def test_bash_action_parsing(self):
        """Test parsing of bash actions with various configurations."""
        test_cases = [
            # Basic command
            ("""<bash>
cmd: "echo 'Hello World'"
</bash>""", BashAction, {"cmd": "echo 'Hello World'", "timeout_secs": 30, "block": True}),
            
            # With timeout
            ("""<bash>
cmd: "sleep 5"
timeout_secs: 10
</bash>""", BashAction, {"cmd": "sleep 5", "timeout_secs": 10}),
            
            # Non-blocking
            ("""<bash>
cmd: "long_running_task.sh"
block: false
timeout_secs: 300
</bash>""", BashAction, {"cmd": "long_running_task.sh", "block": False, "timeout_secs": 300}),
        ]
        
        for xml_content, expected_type, expected_attrs in test_cases:
            actions, errors, found = self.parser.parse_response(xml_content)
            assert len(actions) == 1, f"Expected 1 action, got {len(actions)}"
            assert isinstance(actions[0], expected_type)
            assert not errors, f"Unexpected errors: {errors}"
            
            for attr, value in expected_attrs.items():
                assert getattr(actions[0], attr) == value
    
    def test_todo_batch_operations(self):
        """Test parsing of batch todo operations."""
        xml_content = """<todo>
operations:
  - action: add
    content: "Implement feature X"
  - action: add
    content: "Write tests for feature X"
  - action: complete
    task_id: 1
  - action: delete
    task_id: 2
  - action: view_all
view_all: true
</todo>"""
        
        actions, errors, found = self.parser.parse_response(xml_content)
        assert len(actions) == 1
        assert isinstance(actions[0], BatchTodoAction)
        assert len(actions[0].operations) == 5
        assert actions[0].view_all is True
        assert not errors
        
        # Verify operation details
        ops = actions[0].operations
        assert ops[0].action == "add"
        assert ops[0].content == "Implement feature X"
        assert ops[2].action == "complete"
        assert ops[2].task_id == 1
    
    def test_file_operations(self):
        """Test parsing of various file operations."""
        test_cases = [
            # Read action
            ("""<file>
action: read
file_path: "/path/to/file.txt"
offset: 100
limit: 50
</file>""", ReadAction, {"file_path": "/path/to/file.txt", "offset": 100, "limit": 50}),
            
            # Write action
            ("""<file>
action: write
file_path: "/tmp/output.txt"
content: |
  Line 1
  Line 2
  Line 3
</file>""", WriteAction, {"file_path": "/tmp/output.txt"}),
            
            # Edit action
            ("""<file>
action: edit
file_path: "/src/main.py"
old_string: "def old_function():"
new_string: "def new_function():"
replace_all: true
</file>""", EditAction, {"file_path": "/src/main.py", "replace_all": True}),
            
            # Multi-edit action
            ("""<file>
action: multi_edit
file_path: "/src/config.py"
edits:
  - old_string: "DEBUG = False"
    new_string: "DEBUG = True"
  - old_string: "PORT = 8080"
    new_string: "PORT = 3000"
    replace_all: true
</file>""", MultiEditAction, {"file_path": "/src/config.py"}),
            
            # Metadata action
            ("""<file>
action: metadata
file_paths:
  - "/file1.txt"
  - "/file2.py"
  - "/dir/file3.js"
</file>""", FileMetadataAction, {}),
        ]
        
        for xml_content, expected_type, expected_attrs in test_cases:
            actions, errors, found = self.parser.parse_response(xml_content)
            assert len(actions) == 1, f"Expected 1 action for {expected_type.__name__}"
            assert isinstance(actions[0], expected_type)
            assert not errors, f"Errors for {expected_type.__name__}: {errors}"
            
            for attr, value in expected_attrs.items():
                assert getattr(actions[0], attr) == value
    
    def test_search_operations(self):
        """Test parsing of search operations."""
        test_cases = [
            # Grep action
            ("""<search>
action: grep
pattern: "TODO|FIXME"
path: "/src"
include: "*.py"
</search>""", GrepAction, {"pattern": "TODO|FIXME", "path": "/src", "include": "*.py"}),
            
            # Glob action
            ("""<search>
action: glob
pattern: "**/*.test.js"
path: "/tests"
</search>""", GlobAction, {"pattern": "**/*.test.js", "path": "/tests"}),
          ]
        
        for xml_content, expected_type, expected_attrs in test_cases:
            actions, errors, found = self.parser.parse_response(xml_content)
            assert len(actions) == 1
            assert isinstance(actions[0], expected_type)
            assert not errors
            
            for attr, value in expected_attrs.items():
                assert getattr(actions[0], attr) == value
    
    def test_scratchpad_operations(self):
        """Test parsing of scratchpad operations."""
        test_cases = [
            # Add note
            ("""<scratchpad>
action: add_note
content: "Important observation about the codebase structure"
</scratchpad>""", AddNoteAction, {"content": "Important observation about the codebase structure"}),
            
            # View all notes
            ("""<scratchpad>
action: view_all_notes
</scratchpad>""", ViewAllNotesAction, {}),
        ]
        
        for xml_content, expected_type, expected_attrs in test_cases:
            actions, errors, found = self.parser.parse_response(xml_content)
            assert len(actions) == 1
            assert isinstance(actions[0], expected_type)
            assert not errors
    
    def test_task_management_operations(self):
        """Test parsing of task management operations."""
        # Task create
        xml = """<task_create>
agent_type: explorer
title: "Analyze codebase structure"
description: "Perform a comprehensive analysis of the codebase"
context_refs:
  - "ref1"
  - "ref2"
context_bootstrap:
  - path: "/src/main.py"
    reason: "Entry point of application"
  - path: "/src/config/"
    reason: "Configuration directory"
auto_launch: true
</task_create>"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], TaskCreateAction)
        assert actions[0].agent_type == "explorer"
        assert actions[0].title == "Analyze codebase structure"
        assert len(actions[0].context_refs) == 2
        assert len(actions[0].context_bootstrap) == 2
        assert actions[0].auto_launch is True
        assert not errors
        
        # Add context
        xml = """<add_context>
id: "ctx_analysis_001"
content: "The codebase follows MVC architecture"
reported_by: "analyzer"
task_id: "task_123"
</add_context>"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], AddContextAction)
        assert actions[0].id == "ctx_analysis_001"
        assert not errors
        
        # Launch subagent
        xml = """<launch_subagent>
task_id: "task_456"
</launch_subagent>"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], LaunchSubagentAction)
        assert actions[0].task_id == "task_456"
        assert not errors
    
    def test_report_action(self):
        """Test parsing of report actions."""
        xml = """<report>
contexts:
  - id: "ctx_001"
    content: "Found security vulnerability"
  - id: "ctx_002"
    content: "Performance bottleneck identified"
comments: "Analysis complete with 2 critical findings"
</report>"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], ReportAction)
        assert len(actions[0].contexts) == 2
        assert actions[0].comments == "Analysis complete with 2 critical findings"
        assert not errors
    
    def test_finish_action(self):
        """Test parsing of finish action."""
        xml = """<finish>
Task completed successfully with all tests passing
</finish>"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], FinishAction)
        assert actions[0].message == "Task completed successfully with all tests passing"
        assert not errors
    
    def test_write_temp_script(self):
        """Test parsing of write temp script action."""
        xml = """<write_temp_script>
file_path: "/tmp/test_runner.py"
content: |
  #!/usr/bin/env python3
  import sys
  print("Running tests...")
  sys.exit(0)
</write_temp_script>"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], WriteTempScriptAction)
        assert actions[0].file_path == "/tmp/test_runner.py"
        assert "#!/usr/bin/env python3" in actions[0].content
        assert not errors
    
    def test_multiple_actions_in_response(self):
        """Test parsing multiple actions in a single response."""
        xml = """
Let me help you with that task.

<bash>
cmd: "mkdir -p /tmp/test_dir"
</bash>

Now I'll create a file:

<file>
action: write
file_path: "/tmp/test_dir/README.md"
content: "# Test Project"
</file>

<todo>
operations:
  - action: add
    content: "Complete the implementation"
</todo>

<finish>
Setup completed
</finish>
"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 4
        assert isinstance(actions[0], BashAction)
        assert isinstance(actions[1], WriteAction)
        assert isinstance(actions[2], BatchTodoAction)
        assert isinstance(actions[3], FinishAction)
        assert not errors
    
    def test_error_handling(self):
        """Test parser error handling for malformed inputs."""
        test_cases = [
            # Invalid YAML
            """<bash>
cmd: this is not valid yaml
  because: indentation is wrong
</bash>""",
            
            # Missing required field
            """<file>
action: write
content: "Missing file_path field"
</file>""",
            
            # Invalid action type
            """<file>
action: invalid_action
file_path: "/tmp/file.txt"
</file>""",
            
            # Invalid todo operation
            """<todo>
operations:
  - action: invalid_op
    content: "This won't work"
</todo>""",
        ]
        
        for xml_content in test_cases:
            actions, errors, found = self.parser.parse_response(xml_content)
            assert errors, f"Expected errors for: {xml_content[:50]}..."
            assert found  # Should still detect action attempt
    
    def test_ignored_tags(self):
        """Test that non-action tags are properly ignored."""
        xml = """
<think>
This is my internal reasoning that should be ignored.
</think>

<reasoning>
More internal thoughts here.
</reasoning>

<bash>
cmd: "echo 'Only this should be parsed'"
</bash>

<plan_md>
# My plan
- Step 1
- Step 2
</plan_md>
"""
        
        actions, errors, found = self.parser.parse_response(xml)
        assert len(actions) == 1
        assert isinstance(actions[0], BashAction)
        assert actions[0].cmd == "echo 'Only this should be parsed'"
        assert not errors


class TestActionIntegration:
    """Test integration between parser, handler, and executor."""

    @pytest.mark.asyncio
    async def test_turn_executor_integration(self):
        """Test that parser integrates correctly with TurnExecutor."""
        # Mock command executor
        class MockExecutor:
            async def execute(self, cmd, timeout=None):
                return f"Executed: {cmd}", 0

            async def execute_background(self, cmd):
                return f"Background: {cmd}"
        
        # Create components
        parser = SimpleActionParser()
        todo_manager = TodoManager()
        scratchpad_manager = ScratchpadManager()
        
        action_handler = ActionHandler(
            executor=MockExecutor(),
            todo_manager=todo_manager,
            scratchpad_manager=scratchpad_manager,
            orchestrator_hub=None
        )
        
        turn_executor = TurnExecutor(
            action_parser=parser,
            action_handler=action_handler
        )
        
        # Test execution
        test_input = """
<bash>
cmd: "echo 'Testing integration'"
</bash>

<todo>
operations:
  - action: add
    content: "Test task"
view_all: true
</todo>

<finish>
Integration test complete
</finish>
"""
        
        result = await turn_executor.execute(test_input)

        assert result.done is True
        assert result.finish_message == "Integration test complete"
        assert len(result.actions_executed) == 3
        assert not result.has_error
    
    def test_action_handler_compatibility(self):
        """Test that all action types are handled correctly."""
        parser = SimpleActionParser()
        
        # Parse a comprehensive set of actions
        test_input = """
<bash>cmd: "ls"</bash>
<todo>operations: [{action: add, content: "test"}]</todo>
<file>action: read
file_path: "/test.txt"</file>
<search>action: grep
pattern: "test"</search>
<scratchpad>action: add_note
content: "note"</scratchpad>
<finish>done</finish>
"""
        
        actions, errors, found = parser.parse_response(test_input)
        
        # Verify all actions parsed successfully
        assert len(actions) == 6
        assert not errors
        assert found
        
        # Verify action types
        expected_types = [
            BashAction, BatchTodoAction, ReadAction,
            GrepAction, AddNoteAction, FinishAction
        ]
        
        for action, expected_type in zip(actions, expected_types):
            assert isinstance(action, expected_type)


if __name__ == "__main__":
    # Run basic smoke tests if executed directly
    print("Running action parser tests...")
    
    test_parser = TestActionParser()
    test_parser.setup_method()
    
    # Run a few key tests
    test_parser.test_bash_action_parsing()
    print("✓ Bash action parsing")
    
    test_parser.test_todo_batch_operations()
    print("✓ Todo batch operations")
    
    test_parser.test_file_operations()
    print("✓ File operations")
    
    test_parser.test_multiple_actions_in_response()
    print("✓ Multiple actions parsing")
    
    test_parser.test_error_handling()
    print("✓ Error handling")
    
    test_parser.test_search_operations()
    print("✓ Search operations")
    
    test_parser.test_scratchpad_operations()
    print("✓ Scratchpad operations")
    
    test_parser.test_task_management_operations()
    print("✓ Task management operations")
    
    test_parser.test_report_action()
    print("✓ Report action")
    
    test_parser.test_finish_action()
    print("✓ Finish action")
    
    test_parser.test_write_temp_script()
    print("✓ Write temp script")
    
    test_parser.test_ignored_tags()
    print("✓ Ignored tags")
    
    # Integration tests
    test_integration = TestActionIntegration()
    asyncio.run(test_integration.test_turn_executor_integration())
    print("✓ TurnExecutor integration")
    
    test_integration.test_action_handler_compatibility()
    print("✓ Action handler compatibility")
    
    print("\n✅ All tests passed!")
    