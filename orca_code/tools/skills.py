"""orca_code.tools.skills — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class LoadSkillTool(Tool):
    name = "load_skill"
    description = "Load a skill script"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill file name"}
        }
    }
    required = ['name']
    risk_level = RiskLevel.EXEC

    def execute(self, name: str) -> str:
        from orca_code.tools_skills import load_skill
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return load_skill(**kwargs)


class CreateSkillTool(Tool):
    name = "create_skill"
    description = "Create a new skill"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name"},
            "code": {"type": "string", "description": "Python code"}
        }
    }
    required = ['name', 'code']
    risk_level = RiskLevel.WRITE

    def execute(self, name: str, code: str) -> str:
        from orca_code.tools_skills import create_skill
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return create_skill(**kwargs)


class EditSkillTool(Tool):
    name = "edit_skill"
    description = "Edit a skill script"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name"},
            "code": {"type": "string", "description": "New Python code"}
        }
    }
    required = ['name', 'code']
    risk_level = RiskLevel.WRITE

    def execute(self, name: str, code: str) -> str:
        from orca_code.tools_skills import edit_skill
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return edit_skill(**kwargs)


class ListSkillsTool(Tool):
    name = "list_skills"
    description = "List all skills"
    parameters = {"type": "object", "properties": {}, "required": []}
    required = []
    risk_level = RiskLevel.READ

    def execute(self) -> str:
        from orca_code.tools_skills import list_skills
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return list_skills(**kwargs)


class LoadMdSkillTool(Tool):
    name = "load_md_skill"
    description = "Load a .md behavioral skill"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill file name"}
        }
    }
    required = ['name']
    risk_level = RiskLevel.EXEC

    def execute(self, name: str) -> str:
        from orca_code.tools_skills import load_md_skill
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return load_md_skill(**kwargs)


class ListMdSkillsTool(Tool):
    name = "list_md_skills"
    description = "List all .md behavioral skills"
    parameters = {"type": "object", "properties": {}, "required": []}
    required = []
    risk_level = RiskLevel.READ

    def execute(self) -> str:
        from orca_code.tools_skills import list_md_skills
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return list_md_skills(**kwargs)


def register_skills_tools(registry) -> int:
    """Register all skills tools. Returns count of new registrations."""
    tools = [LoadSkillTool(), CreateSkillTool(), EditSkillTool(), ListSkillsTool(), LoadMdSkillTool(), ListMdSkillsTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
