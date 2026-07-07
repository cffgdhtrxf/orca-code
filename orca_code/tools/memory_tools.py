"""orca_code.tools.memory_tools — Memory and profile tools (class-based wrappers)."""
from __future__ import annotations
from orca_code.permissions import RiskLevel
from orca_code.tools.base import Tool

class RecallConversationTool(Tool):
    name = "recall_conversation"
    description = "Search past conversation history via FTS5"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keywords"},
            "limit": {"type": "integer", "description": "Max results 1-20, default 5"},
        },
    }
    required = ["query"]
    risk_level = RiskLevel.READ
    def execute(self, query: str, limit: int = 5) -> str:
        from orca_code.tools_memory import recall_conversation
        return recall_conversation(query, limit)

class UpdateProfileTool(Tool):
    name = "update_profile"
    description = "Add a note to the user profile"
    parameters = {
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "What you learned about the user"},
        },
    }
    required = ["note"]
    risk_level = RiskLevel.WRITE
    def execute(self, note: str) -> str:
        from orca_code.tools_memory import update_profile
        return update_profile(note)

def register_memory_tools(registry) -> int:
    tools = [RecallConversationTool(), UpdateProfileTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
