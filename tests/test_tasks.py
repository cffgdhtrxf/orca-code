"""Tests for tools/tasks.py — Task scheduling tool class wrappers."""

import pytest
from orca_code.tools.base import ToolRegistry
from orca_code.tools.tasks import (
    AddTaskTool, ListTasksTool, RemoveTaskTool, register_tasks_tools,
)
from orca_code.permissions import RiskLevel


class TestTaskTools:
    """Verify task tool classes."""

    def test_add_task_schema(self):
        schema = AddTaskTool.to_openai_schema()
        assert schema["function"]["name"] == "add_task"
        assert "name" in schema["function"]["parameters"]["properties"]
        assert "schedule" in schema["function"]["parameters"]["properties"]

    def test_list_tasks_schema(self):
        schema = ListTasksTool.to_openai_schema()
        assert schema["function"]["name"] == "list_tasks"

    def test_remove_task_schema(self):
        schema = RemoveTaskTool.to_openai_schema()
        assert schema["function"]["name"] == "remove_task"

    def test_risk_levels(self):
        assert AddTaskTool.risk_level == RiskLevel.WRITE
        assert ListTasksTool.risk_level == RiskLevel.READ
        assert RemoveTaskTool.risk_level == RiskLevel.WRITE

    def test_validate_missing_required(self):
        err = AddTaskTool.validate_args({})
        assert err is not None
        assert "name" in err.lower() or "schedule" in err.lower() or "mode" in err.lower() or "action" in err.lower()

    def test_validate_valid(self):
        err = AddTaskTool.validate_args({
            "name": "test", "mode": "interval",
            "schedule": "60", "action": "execute_command",
        })
        assert err is None


class TestTaskRegistry:
    """Verify task tools register correctly."""

    def test_register_all(self):
        registry = ToolRegistry()
        count = register_tasks_tools(registry)
        assert count == 3
        assert "add_task" in registry
        assert "list_tasks" in registry
        assert "remove_task" in registry

    def test_idempotent(self):
        registry = ToolRegistry()
        first = register_tasks_tools(registry)
        second = register_tasks_tools(registry)
        assert second == 0
        assert len(registry) == 3


class TestTaskToolExecution:
    """Verify task tools execute via the flat function wrappers."""

    def test_list_tasks_returns_string(self):
        """list_tasks should return a string (empty or with tasks)."""
        tool = ListTasksTool()
        result = tool.execute()
        assert isinstance(result, str)

    def test_remove_nonexistent_task(self):
        """Removing a non-existent task returns error string."""
        tool = RemoveTaskTool()
        result = tool.execute(name="nonexistent_task_xyz")
        assert isinstance(result, str)
        assert "不存在" in result or "not found" in result.lower() or "错误" in result
