"""orca_code.tools.extended — Tool class wrappers."""

from __future__ import annotations

from orca_code.permissions import RiskLevel
from orca_code.tools.base import Tool


class SpeakTextTool(Tool):
    name = "speak_text"
    description = "Speak text via TTS"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to speak"}
        }
    }
    required = ['text']
    risk_level = RiskLevel.WRITE

    def execute(self, text: str) -> str:
        from orca_code.tts_mcp import speak_text
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return speak_text(**kwargs)


class AgentOpenTool(Tool):
    name = "agent_open"
    description = "Launch background sub-agent"
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Task"},
            "tools": {"type": "string", "description": "Tool names"},
            "context": {"type": "string", "description": "Extra context"}
        }
    }
    required = ['task']
    risk_level = RiskLevel.EXEC

    def execute(self, task: str, tools: str = None, context: str = None) -> str:
        from orca_code.subagent import agent_open
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return agent_open(**kwargs)


class AgentEvalTool(Tool):
    name = "agent_eval"
    description = "Get sub-agent result"
    parameters = {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "Handle"},
            "timeout": {"type": "integer", "description": "Timeout"}
        }
    }
    required = ['handle']
    risk_level = RiskLevel.READ

    def execute(self, handle: str, timeout: str = None) -> str:
        from orca_code.subagent import agent_eval
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return agent_eval(**kwargs)


class AgentCloseTool(Tool):
    name = "agent_close"
    description = "Terminate sub-agent"
    parameters = {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "Handle"}
        }
    }
    required = ['handle']
    risk_level = RiskLevel.WRITE

    def execute(self, handle: str) -> str:
        from orca_code.subagent import agent_close
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return agent_close(**kwargs)


class ExecutePythonTool(Tool):
    name = "execute_python"
    description = "Execute Python in REPL"
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code"},
            "timeout": {"type": "integer", "description": "Timeout"}
        }
    }
    required = ['code']
    risk_level = RiskLevel.EXEC

    def execute(self, code: str, timeout: str = None) -> str:
        from _python_repl import execute_python
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return execute_python(**kwargs)


class LspDiagnosticsTool(Tool):
    name = "lsp_diagnostics"
    description = "Get LSP diagnostics"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File path"}
        }
    }
    required = ['file_path']
    risk_level = RiskLevel.READ

    def execute(self, file_path: str) -> str:
        from orca_code.lsp import lsp_diagnostics
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return lsp_diagnostics(**kwargs)


class LspReferencesTool(Tool):
    name = "lsp_references"
    description = "Find symbol references via LSP"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File path"},
            "line": {"type": "integer", "description": "Line"},
            "column": {"type": "integer", "description": "Column"}
        }
    }
    required = ['file_path', 'line']
    risk_level = RiskLevel.READ

    def execute(self, file_path: str, line: str, column: str = None) -> str:
        from orca_code.lsp import lsp_references
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return lsp_references(**kwargs)


class LspDefinitionTool(Tool):
    name = "lsp_definition"
    description = "Go to definition via LSP"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File path"},
            "line": {"type": "integer", "description": "Line"},
            "column": {"type": "integer", "description": "Column"}
        }
    }
    required = ['file_path', 'line']
    risk_level = RiskLevel.READ

    def execute(self, file_path: str, line: str, column: str = None) -> str:
        from orca_code.lsp import lsp_definition
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return lsp_definition(**kwargs)


def register_extended_tools(registry) -> int:
    """Register all extended tools. Returns count of new registrations."""
    tools = [SpeakTextTool(), AgentOpenTool(), AgentEvalTool(), AgentCloseTool(), ExecutePythonTool(), LspDiagnosticsTool(), LspReferencesTool(), LspDefinitionTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
