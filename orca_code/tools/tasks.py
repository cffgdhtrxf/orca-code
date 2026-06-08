"""orca_code.tools.tasks — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class AddTaskTool(Tool):
    name = "add_task"
    description = "Add scheduled task"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Task name"},
            "mode": {"type": "string", "description": "interval or cron"},
            "schedule": {"type": "string", "description": "Schedule"},
            "action": {"type": "string", "description": "Action type"},
            "params": {"type": "string", "description": "JSON params"}
        }
    }
    required = ['name', 'mode', 'schedule', 'action']
    risk_level = RiskLevel.WRITE

    def execute(self, name: str, mode: str, schedule: str, action: str, params: str = None) -> str:
        from orca_code.tools_skills import add_task
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return add_task(**kwargs)


class ListTasksTool(Tool):
    name = "list_tasks"
    description = "List all scheduled tasks"
    parameters = {"type": "object", "properties": {}, "required": []}
    required = []
    risk_level = RiskLevel.READ

    def execute(self) -> str:
        from orca_code.tools_skills import list_tasks
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return list_tasks(**kwargs)


class RemoveTaskTool(Tool):
    name = "remove_task"
    description = "Remove a scheduled task"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Task name"}
        }
    }
    required = ['name']
    risk_level = RiskLevel.WRITE

    def execute(self, name: str) -> str:
        from orca_code.tools_skills import remove_task
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return remove_task(**kwargs)


def register_tasks_tools(registry) -> int:
    """Register all tasks tools. Returns count of new registrations."""
    tools = [AddTaskTool(), ListTasksTool(), RemoveTaskTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
