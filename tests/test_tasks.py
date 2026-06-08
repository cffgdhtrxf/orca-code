"""Tests for tools/tasks.py — Claude Code task state machine."""

import json
import tempfile
from pathlib import Path
import pytest
from orca_code.tools.tasks import (
    Task, TaskStatus, TaskStore,
    TaskCreateTool, TaskUpdateTool, TaskGetTool, TaskListTool,
    register_task_tools, get_task_store,
)
from orca_code.tools.base import ToolRegistry


class TestTaskModel:
    """Verify the Task data model."""

    def test_create_task(self):
        t = Task(subject="Fix auth bug", description="The login is broken")
        assert len(t.id) == 8
        assert t.subject == "Fix auth bug"
        assert t.status == TaskStatus.PENDING
        assert t.blocked_by == []
        assert t.blocks == []

    def test_task_to_dict_and_back(self):
        t = Task(subject="Test", description="Desc", active_form="Testing")
        t.blocked_by = ["abc12345"]
        d = t.to_dict()
        t2 = Task.from_dict(d)
        assert t2.subject == "Test"
        assert t2.blocked_by == ["abc12345"]

    def test_can_start_when_pending(self):
        t = Task(subject="X", description="Y")
        assert t.can_start() is True

    def test_is_active(self):
        t = Task(subject="X", description="Y")
        assert t.is_active() is True
        t.status = TaskStatus.COMPLETED
        assert t.is_active() is False


class TestTaskStore:
    """Verify TaskStore persistence and operations."""

    def test_add_and_get(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        t = Task(subject="Test", description="Testing")
        store.add(t)
        assert store.get(t.id) is not None
        assert store.get(t.id).subject == "Test"

    def test_list_active_excludes_deleted(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        t1 = store.add(Task(subject="Active", description=""))
        t2 = store.add(Task(subject="Deleted", description=""))
        store.update(t2.id, status="deleted")
        active = store.list_active()
        assert len(active) == 1
        assert active[0].id == t1.id

    def test_list_by_status(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        store.add(Task(subject="P1", description=""))
        store.add(Task(subject="P2", description=""))
        pending = store.list_by_status("pending")
        assert len(pending) == 2

    def test_update_status(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        t = store.add(Task(subject="Test", description=""))
        store.update(t.id, status="in_progress")
        assert store.get(t.id).status == TaskStatus.IN_PROGRESS

    def test_update_nonexistent(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        assert store.update("nonexistent", status="completed") is None

    def test_dependency_blocked_by(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        t1 = store.add(Task(subject="Blocker", description="Must finish first"))
        t2 = store.add(Task(subject="Dependent", description="Depends on blocker"))
        store.add_blocked_by(t2.id, t1.id)
        t2_refreshed = store.get(t2.id)
        t1_refreshed = store.get(t1.id)
        assert t1.id in t2_refreshed.blocked_by
        assert t2.id in t1_refreshed.blocks

    def test_persistence_roundtrip(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        store1 = TaskStore(path)
        t = store1.add(Task(subject="Persist", description="Test persistence"))
        store1.update(t.id, status="in_progress")

        # New store reads from same file
        store2 = TaskStore(path)
        t2 = store2.get(t.id)
        assert t2 is not None
        assert t2.subject == "Persist"
        assert t2.status == TaskStatus.IN_PROGRESS

        # Cleanup
        path.unlink(missing_ok=True)


class TestTaskCreateTool:
    """Verify TaskCreateTool."""

    def test_create_task(self):
        tool = TaskCreateTool()
        result = tool.execute(subject="Test task", description="Do something")
        assert "Task created:" in result
        assert "Test task" in result
        assert "pending" in result

    def test_create_task_with_metadata(self):
        tool = TaskCreateTool()
        result = tool.execute(
            subject="Meta task",
            description="With metadata",
            metadata={"priority": "high"},
        )
        assert "Task created:" in result


class TestTaskUpdateTool:
    """Verify TaskUpdateTool."""

    def test_update_status(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        t = store.add(Task(subject="Test", description=""))

        tool = TaskUpdateTool()
        # Override global store
        import orca_code.tools.tasks as tmod
        old_store = tmod._task_store
        tmod._task_store = store

        try:
            result = tool.execute(taskId=t.id, status="in_progress")
            assert "in_progress" in result
            t_refreshed = store.get(t.id)
            assert t_refreshed.status == TaskStatus.IN_PROGRESS
        finally:
            tmod._task_store = old_store

    def test_update_nonexistent(self):
        tool = TaskUpdateTool()
        result = tool.execute(taskId="nonexistent")
        assert "not found" in result


class TestTaskListTool:
    """Verify TaskListTool."""

    def test_list_empty(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        import orca_code.tools.tasks as tmod
        old_store = tmod._task_store
        tmod._task_store = store
        try:
            tool = TaskListTool()
            result = tool.execute()
            assert "No tasks found" in result
        finally:
            tmod._task_store = old_store

    def test_list_with_tasks(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        store.add(Task(subject="Task 1", description=""))
        store.add(Task(subject="Task 2", description=""))

        import orca_code.tools.tasks as tmod
        old_store = tmod._task_store
        tmod._task_store = store
        try:
            tool = TaskListTool()
            result = tool.execute()
            assert "Task 1" in result
            assert "Task 2" in result
        finally:
            tmod._task_store = old_store


class TestTaskGetTool:
    """Verify TaskGetTool."""

    def test_get_task(self):
        store = TaskStore(Path(tempfile.mktemp(suffix=".json")))
        t = store.add(Task(subject="Detail task", description="Detailed description"))

        import orca_code.tools.tasks as tmod
        old_store = tmod._task_store
        tmod._task_store = store
        try:
            tool = TaskGetTool()
            result = tool.execute(taskId=t.id)
            assert "Detail task" in result
            assert "Detailed description" in result
        finally:
            tmod._task_store = old_store


class TestRegisterTaskTools:
    """Verify task tool registration."""

    def test_registers_four_tools(self):
        registry = ToolRegistry()
        count = register_task_tools(registry)
        assert count == 4
        names = registry.list_names()
        assert "task_create" in names
        assert "task_update" in names
        assert "task_get" in names
        assert "task_list" in names

    def test_idempotent(self):
        registry = ToolRegistry()
        first = register_task_tools(registry)
        second = register_task_tools(registry)
        assert first == 4
        assert second == 0  # Idempotent
