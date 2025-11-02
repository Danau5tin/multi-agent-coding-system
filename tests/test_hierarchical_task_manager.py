"""Comprehensive tests for HierarchicalTaskManager implementation."""

import pytest
from unittest.mock import patch
from multi_agent_coding_system.agents.actions.hierarchical_task_manager import HierarchicalTaskManager
from multi_agent_coding_system.agents.actions.entities.task import Task, TaskStatus


class TestHierarchicalTaskManager:
    """Test suite for HierarchicalTaskManager functionality."""
    
    def setup_method(self):
        """Set up test fixtures before each test."""
        self.manager = HierarchicalTaskManager()
        self.orchestrator_id = "orchestrator_001"
        self.subagent1_id = "subagent_001"
        self.subagent2_id = "subagent_002"
        self.subsubagent_id = "subsubagent_001"
    
    # ========== Task Creation Tests ==========
    
    def test_create_root_task(self):
        """Test creating a root task."""
        task_id = self.manager.create_task(
            title="Root Task",
            description="A root level task",
            owner_id=self.orchestrator_id,
            max_turns=10,
            agent_type="explorer"
        )
        
        assert task_id == "task_001"
        task = self.manager.get_task(task_id)
        assert task is not None
        assert task.title == "Root Task"
        assert task.owner_id == self.orchestrator_id
        assert task.depth == 0
        assert task.parent_id is None
        assert task.child_ids == []
    
    def test_create_subtask(self):
        """Test creating a subtask under a parent."""
        # Create parent
        parent_id = self.manager.create_task(
            title="Parent Task",
            description="Parent",
            owner_id=self.orchestrator_id,
            max_turns=10
        )

        # Create subtask
        child_id = self.manager.create_subtask(
            parent_id=parent_id,
            title="Child Task",
            description="Child",
            owner_id=self.subagent1_id,
            max_turns=10
        )
        
        assert child_id == "task_002"
        
        # Check child properties
        child = self.manager.get_task(child_id)
        assert child.parent_id == parent_id
        assert child.depth == 1
        assert child.owner_id == self.subagent1_id
        
        # Check parent was updated
        parent = self.manager.get_task(parent_id)
        assert child_id in parent.child_ids
    
    def test_create_multiple_subtasks(self):
        """Test creating multiple subtasks under same parent."""
        parent_id = self.manager.create_task(
            title="Parent",
            description="Parent task",
            owner_id=self.orchestrator_id,
            max_turns=10
        )

        child1_id = self.manager.create_subtask(
            parent_id=parent_id,
            title="Child 1",
            description="First child",
            owner_id=self.subagent1_id,
            max_turns=10
        )

        child2_id = self.manager.create_subtask(
            parent_id=parent_id,
            title="Child 2",
            description="Second child",
            owner_id=self.subagent2_id,
            max_turns=10
        )
        
        parent = self.manager.get_task(parent_id)
        assert len(parent.child_ids) == 2
        assert child1_id in parent.child_ids
        assert child2_id in parent.child_ids
    
    def test_max_depth_enforcement(self):
        """Test that depth limit is enforced."""
        # Create root (depth 0)
        root_id = self.manager.create_task(
            title="Root",
            description="Root",
            owner_id=self.orchestrator_id,
            max_turns=10
        )

        # Create child (depth 1)
        child_id = self.manager.create_subtask(
            parent_id=root_id,
            title="Child",
            description="Child",
            owner_id=self.subagent1_id,
            max_turns=10
        )

        # Create grandchild (depth 2)
        grandchild_id = self.manager.create_subtask(
            parent_id=child_id,
            title="Grandchild",
            description="Grandchild",
            owner_id=self.subsubagent_id,
            max_turns=10
        )

        # Attempt to create great-grandchild (would be depth 3) - should fail
        with pytest.raises(ValueError, match="Maximum depth.*exceeded"):
            self.manager.create_subtask(
                parent_id=grandchild_id,
                title="Great-grandchild",
                description="Too deep",
                owner_id="agent_004",
                max_turns=10
            )
    
    def test_create_subtask_nonexistent_parent(self):
        """Test creating subtask with non-existent parent fails."""
        with pytest.raises(ValueError, match="Parent task.*does not exist"):
            self.manager.create_subtask(
                parent_id="nonexistent",
                title="Orphan",
                description="No parent",
                owner_id=self.subagent1_id,
                max_turns=10
            )
    
    # ========== Status Update Tests ==========
    
    def test_update_status_by_owner(self):
        """Test that owner can update task status."""
        task_id = self.manager.create_task(
            title="Test Task",
            description="Test",
            owner_id=self.orchestrator_id,
            max_turns=10
        )
        
        success = self.manager.update_status(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            owner_id=self.orchestrator_id
        )
        
        assert success is True
        task = self.manager.get_task(task_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
    
    def test_update_status_by_non_owner_fails(self):
        """Test that non-owner cannot update task status."""
        task_id = self.manager.create_task(
            title="Test Task",
            description="Test",
            owner_id=self.orchestrator_id,
            max_turns=10
        )
        
        with pytest.raises(PermissionError, match="cannot modify task"):
            self.manager.update_status(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                owner_id=self.subagent1_id  # Different agent
            )
    
    def test_update_status_with_error(self):
        """Test updating status with error message."""
        task_id = self.manager.create_task(
            title="Test Task",
            description="Test",
            owner_id=self.orchestrator_id,
            max_turns=10
        )
        
        self.manager.update_status(
            task_id=task_id,
            status=TaskStatus.FAILED,
            owner_id=self.orchestrator_id,
            error_message="Something went wrong"
        )
        
        task = self.manager.get_task(task_id)
        assert task.status == TaskStatus.FAILED
        assert task.error_message == "Something went wrong"
    
    def test_update_nonexistent_task(self):
        """Test updating non-existent task fails."""
        with pytest.raises(ValueError, match="Task.*does not exist"):
            self.manager.update_status(
                task_id="nonexistent",
                status=TaskStatus.COMPLETED,
                owner_id=self.orchestrator_id
            )
    
    # ========== Read Operation Tests ==========
    
    def test_get_children(self):
        """Test retrieving children of a task."""
        parent_id = self.manager.create_task(
            title="Parent",
            description="Parent",
            owner_id=self.orchestrator_id,
            max_turns=10
        )

        child1_id = self.manager.create_subtask(
            parent_id=parent_id,
            title="Child 1",
            description="Child 1",
            owner_id=self.subagent1_id,
            max_turns=10
        )

        child2_id = self.manager.create_subtask(
            parent_id=parent_id,
            title="Child 2",
            description="Child 2",
            owner_id=self.subagent2_id,
            max_turns=10
        )
        
        children = self.manager.get_children(parent_id)
        assert len(children) == 2
        child_ids = [c.task_id for c in children]
        assert child1_id in child_ids
        assert child2_id in child_ids
    
    def test_get_owned_tasks(self):
        """Test retrieving all tasks owned by an agent."""
        # Create tasks owned by different agents
        task1 = self.manager.create_task(
            title="Task 1",
            description="Owned by orchestrator",
            owner_id=self.orchestrator_id,
            max_turns=10
        )

        task2 = self.manager.create_task(
            title="Task 2",
            description="Also owned by orchestrator",
            owner_id=self.orchestrator_id,
            max_turns=10
        )

        task3 = self.manager.create_task(
            title="Task 3",
            description="Owned by subagent",
            owner_id=self.subagent1_id,
            max_turns=10
        )
        
        # Get orchestrator's tasks
        orchestrator_tasks = self.manager.get_owned_tasks(self.orchestrator_id)
        assert len(orchestrator_tasks) == 2
        task_ids = [t.task_id for t in orchestrator_tasks]
        assert task1 in task_ids
        assert task2 in task_ids
        
        # Get subagent's tasks
        subagent_tasks = self.manager.get_owned_tasks(self.subagent1_id)
        assert len(subagent_tasks) == 1
        assert subagent_tasks[0].task_id == task3
    
    def test_can_modify(self):
        """Test permission checking."""
        task_id = self.manager.create_task(
            title="Test Task",
            description="Test",
            owner_id=self.orchestrator_id,
            max_turns=10
        )
        
        # Owner can modify
        assert self.manager.can_modify(task_id, self.orchestrator_id) is True
        
        # Non-owner cannot modify
        assert self.manager.can_modify(task_id, self.subagent1_id) is False
        
        # Non-existent task
        assert self.manager.can_modify("nonexistent", self.orchestrator_id) is False
    
    def test_get_all_tasks(self):
        """Test retrieving all tasks."""
        task1 = self.manager.create_task("Task 1", "Desc 1", self.orchestrator_id, max_turns=10)
        task2 = self.manager.create_task("Task 2", "Desc 2", self.subagent1_id, max_turns=10)
        task3 = self.manager.create_task("Task 3", "Desc 3", self.subagent2_id, max_turns=10)
        
        all_tasks = self.manager.get_all_tasks()
        assert len(all_tasks) == 3
        task_ids = [t.task_id for t in all_tasks]
        assert task1 in task_ids
        assert task2 in task_ids
        assert task3 in task_ids
    
    # ========== Tree Structure Tests ==========
    
    def test_get_tree_single_root(self):
        """Test getting tree structure for a single root."""
        root_id = self.manager.create_task("Root", "Root", self.orchestrator_id, max_turns=10)
        child1_id = self.manager.create_subtask(root_id, "Child 1", "C1", max_turns=10, owner_id=self.subagent1_id)
        child2_id = self.manager.create_subtask(root_id, "Child 2", "C2", max_turns=10, owner_id=self.subagent2_id)
        grandchild_id = self.manager.create_subtask(child1_id, "Grandchild", "GC", max_turns=10, owner_id=self.subsubagent_id)
        
        tree = self.manager.get_tree(root_id)
        
        assert tree['task_id'] == root_id
        assert tree['title'] == "Root"
        assert len(tree['children']) == 2
        
        # Find child1 in tree
        child1_tree = next(c for c in tree['children'] if c['task_id'] == child1_id)
        assert len(child1_tree['children']) == 1
        assert child1_tree['children'][0]['task_id'] == grandchild_id
    
    def test_get_tree_all_roots(self):
        """Test getting all trees when no root specified."""
        root1_id = self.manager.create_task("Root 1", "R1", self.orchestrator_id, max_turns=10)
        root2_id = self.manager.create_task("Root 2", "R2", self.orchestrator_id, max_turns=10)
        child_id = self.manager.create_subtask(root1_id, "Child", "C", max_turns=10, owner_id=self.subagent1_id)
        
        all_trees = self.manager.get_tree()
        
        assert 'trees' in all_trees
        assert len(all_trees['trees']) == 2
        
        tree_ids = [t['task_id'] for t in all_trees['trees']]
        assert root1_id in tree_ids
        assert root2_id in tree_ids
    
    # ========== Status Aggregation Tests ==========
    
    def test_aggregated_status_leaf_task(self):
        """Test aggregated status for leaf task returns its own status."""
        task_id = self.manager.create_task("Leaf", "Leaf task", self.orchestrator_id, max_turns=10)
        self.manager.update_status(task_id, TaskStatus.COMPLETED, self.orchestrator_id)
        
        agg_status = self.manager.get_aggregated_status(task_id)
        assert agg_status == TaskStatus.COMPLETED
    
    def test_aggregated_status_all_children_completed(self):
        """Test parent shows completed when all children completed."""
        parent_id = self.manager.create_task("Parent", "Parent", self.orchestrator_id, max_turns=10)
        child1_id = self.manager.create_subtask(parent_id, "Child 1", "C1", max_turns=10, owner_id=self.subagent1_id)
        child2_id = self.manager.create_subtask(parent_id, "Child 2", "C2", max_turns=10, owner_id=self.subagent2_id)
        
        # Complete both children
        self.manager.update_status(child1_id, TaskStatus.COMPLETED, self.subagent1_id)
        self.manager.update_status(child2_id, TaskStatus.COMPLETED, self.subagent2_id)
        
        agg_status = self.manager.get_aggregated_status(parent_id)
        assert agg_status == TaskStatus.COMPLETED
    
    def test_aggregated_status_any_child_in_progress(self):
        """Test parent shows in_progress when any child is not completed."""
        parent_id = self.manager.create_task("Parent", "Parent", self.orchestrator_id, max_turns=10)
        child1_id = self.manager.create_subtask(parent_id, "Child 1", "C1", max_turns=10, owner_id=self.subagent1_id)
        child2_id = self.manager.create_subtask(parent_id, "Child 2", "C2", max_turns=10, owner_id=self.subagent2_id)
        
        # Complete one child, leave other in created state
        self.manager.update_status(child1_id, TaskStatus.COMPLETED, self.subagent1_id)
        # child2 remains in CREATED state
        
        agg_status = self.manager.get_aggregated_status(parent_id)
        assert agg_status == TaskStatus.CREATED  # Shows as in progress
    
    def test_aggregated_status_with_failed_child(self):
        """Test parent status when a child has failed."""
        parent_id = self.manager.create_task("Parent", "Parent", self.orchestrator_id, max_turns=10)
        child1_id = self.manager.create_subtask(parent_id, "Child 1", "C1", max_turns=10, owner_id=self.subagent1_id)
        child2_id = self.manager.create_subtask(parent_id, "Child 2", "C2", max_turns=10, owner_id=self.subagent2_id)
        
        self.manager.update_status(child1_id, TaskStatus.COMPLETED, self.subagent1_id)
        self.manager.update_status(child2_id, TaskStatus.FAILED, self.subagent2_id, "Error occurred")
        
        agg_status = self.manager.get_aggregated_status(parent_id)
        assert agg_status == TaskStatus.CREATED  # Shows as not all completed
    
    # ========== Thread Safety Tests ==========
    
    def test_concurrent_task_creation(self):
        """Test thread-safe concurrent task creation."""
        import threading
        import time
        
        task_ids = []
        lock = threading.Lock()
        
        def create_task(agent_id):
            task_id = self.manager.create_task(
                title=f"Task by {agent_id}",
                description="Concurrent task",
                owner_id=agent_id,
                max_turns=10
            )
            with lock:
                task_ids.append(task_id)
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=create_task, args=(f"agent_{i}",))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # All tasks should be created with unique IDs
        assert len(task_ids) == 10
        assert len(set(task_ids)) == 10  # All unique
        
        # Task counter should be correct
        assert self.manager.task_counter == 10
    
    # ========== Display Tests ==========
    
    def test_format_tree_display(self):
        """Test formatting task tree for display."""
        root_id = self.manager.create_task("Root Task", "Root", self.orchestrator_id, max_turns=10)
        child1_id = self.manager.create_subtask(root_id, "Child 1", "C1", max_turns=10, owner_id=self.subagent1_id)
        child2_id = self.manager.create_subtask(root_id, "Child 2", "C2", max_turns=10, owner_id=self.subagent2_id)
        grandchild_id = self.manager.create_subtask(child1_id, "Grandchild", "GC", max_turns=10, owner_id=self.subsubagent_id)
        
        # Update some statuses
        self.manager.update_status(grandchild_id, TaskStatus.COMPLETED, self.subsubagent_id)
        self.manager.update_status(child2_id, TaskStatus.FAILED, self.subagent2_id, "Test error")
        
        display = self.manager.format_tree_display()
        
        # Check that all tasks appear in display
        assert "Root Task" in display
        assert "Child 1" in display
        assert "Child 2" in display
        assert "Grandchild" in display
        
        # Check error message appears
        assert "Test error" in display
        
        # Check proper indentation (children indented more than parents)
        lines = display.split('\n')
        root_line = next(l for l in lines if "Root Task" in l)
        child_line = next(l for l in lines if "Child 1" in l)
        assert len(child_line) - len(child_line.lstrip()) > len(root_line) - len(root_line.lstrip())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])