"""orca_code.tools.core — Core tool implementations using the Tool base class.

Each tool wraps an existing flat function from orca_code.tools_core.
This provides the class-based interface while reusing proven implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read file (auto-detect encoding)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件绝对路径"},
        },
    }
    required = ["path"]
    risk_level = RiskLevel.READ

    def execute(self, path: str) -> str:
        from orca_code.tools_core import read_file
        return read_file(path)


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create/overwrite file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
    }
    required = ["path", "content"]
    risk_level = RiskLevel.WRITE

    def execute(self, path: str, content: str) -> str:
        from orca_code.tools_core import write_file
        return write_file(path, content)


class EditFileTool(Tool):
    name = "edit_file"
    description = "Precise string replacement in a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_string": {"type": "string", "description": "要替换的文本（必须唯一）"},
            "new_string": {"type": "string", "description": "替换后的文本"},
        },
    }
    required = ["path", "old_string", "new_string"]
    risk_level = RiskLevel.WRITE

    def execute(self, path: str, old_string: str, new_string: str) -> str:
        from orca_code.tools_core import edit_file
        return edit_file(path, old_string, new_string)


class ApplyDiffTool(Tool):
    name = "apply_diff"
    description = "Apply a unified diff to a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "diff_text": {"type": "string", "description": "Unified diff 文本"},
        },
    }
    required = ["path", "diff_text"]
    risk_level = RiskLevel.WRITE

    def execute(self, path: str, diff_text: str) -> str:
        from orca_code.tools_core import apply_diff
        return apply_diff(path, diff_text)


class ListFilesTool(Tool):
    name = "list_files"
    description = "List files and subdirectories"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录绝对路径"},
        },
    }
    required = []
    risk_level = RiskLevel.READ

    def execute(self, path: str = None) -> str:
        from orca_code.tools_core import list_files
        return list_files(path)


class SearchFilesTool(Tool):
    name = "search_files"
    description = "Search files by glob pattern"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
            "directory": {"type": "string", "description": "搜索起始目录"},
        },
    }
    required = ["pattern"]
    risk_level = RiskLevel.READ

    def execute(self, pattern: str, directory: str = None) -> str:
        from orca_code.tools_core import search_files
        return search_files(pattern, directory)


class SearchContentTool(Tool):
    name = "search_content"
    description = "Search text in files"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "搜索文本或正则"},
            "directory": {"type": "string", "description": "搜索目录"},
            "file_filter": {"type": "string", "description": "文件名过滤，如 *.py"},
        },
    }
    required = ["pattern"]
    risk_level = RiskLevel.READ

    def execute(self, pattern: str, directory: str = None, file_filter: str = None) -> str:
        from orca_code.tools_core import search_content
        return search_content(pattern, directory, file_filter)


class ExecuteCommandTool(Tool):
    name = "execute_command"
    description = "Run a shell command and return output"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "working_dir": {"type": "string", "description": "工作目录"},
        },
    }
    required = ["command"]
    risk_level = RiskLevel.EXEC

    def execute(self, command: str, working_dir: str = None) -> str:
        from orca_code.tools_core import execute_command
        return execute_command(command, working_dir)


class GetSystemInfoTool(Tool):
    name = "get_system_info"
    description = "Get system hardware and runtime info"
    parameters = {"type": "object", "properties": {}, "required": []}
    required = []
    risk_level = RiskLevel.READ

    def execute(self) -> str:
        from orca_code.tools_core import get_system_info
        return get_system_info()


# ── Registry ──────────────────────────────────────────────────────────────────

def register_core_tools(registry) -> int:
    """Register all core tools into a ToolRegistry. Returns count of new registrations.

    Idempotent: returns 0 if tools are already registered.
    """
    tools = [
        ReadFileTool(), WriteFileTool(), EditFileTool(), ApplyDiffTool(),
        ListFilesTool(), SearchFilesTool(), SearchContentTool(),
        ExecuteCommandTool(), GetSystemInfoTool(),
    ]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
