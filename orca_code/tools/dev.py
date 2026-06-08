"""orca_code.tools.dev — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class GitStatusTool(Tool):
    name = "git_status"
    description = "Git status"
    parameters = {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repo path"}
        }
    }
    required = []
    risk_level = RiskLevel.READ

    def execute(self, repo_path: str = None) -> str:
        from orca_code.tools_dev import git_status
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return git_status(**kwargs)


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Git diff"
    parameters = {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repo path"},
            "staged": {"type": "boolean", "description": "Staged only"}
        }
    }
    required = []
    risk_level = RiskLevel.READ

    def execute(self, repo_path: str = None, staged: str = None) -> str:
        from orca_code.tools_dev import git_diff
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return git_diff(**kwargs)


class GitLogTool(Tool):
    name = "git_log"
    description = "Git log"
    parameters = {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repo path"},
            "max_count": {"type": "integer", "description": "Max entries"}
        }
    }
    required = []
    risk_level = RiskLevel.READ

    def execute(self, repo_path: str = None, max_count: str = None) -> str:
        from orca_code.tools_dev import git_log
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return git_log(**kwargs)


class GitBlameTool(Tool):
    name = "git_blame"
    description = "Git blame"
    parameters = {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "Repo path"},
            "file": {"type": "string", "description": "File path"}
        }
    }
    required = ['file']
    risk_level = RiskLevel.READ

    def execute(self, file: str, repo_path: str = None) -> str:
        from orca_code.tools_dev import git_blame
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return git_blame(**kwargs)


class GoToDefinitionTool(Tool):
    name = "go_to_definition"
    description = "Find symbol definition"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File path"},
            "line": {"type": "integer", "description": "Line"},
            "column": {"type": "integer", "description": "Column"},
            "symbol": {"type": "string", "description": "Symbol"}
        }
    }
    required = ['file_path']
    risk_level = RiskLevel.READ

    def execute(self, file_path: str, line: str = None, column: str = None, symbol: str = None) -> str:
        from orca_code.tools_dev import go_to_definition
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return go_to_definition(**kwargs)


class FindReferencesTool(Tool):
    name = "find_references"
    description = "Find symbol references"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol"},
            "directory": {"type": "string", "description": "Search dir"},
            "file_filter": {"type": "string", "description": "File filter"}
        }
    }
    required = ['symbol']
    risk_level = RiskLevel.READ

    def execute(self, symbol: str, directory: str = None, file_filter: str = None) -> str:
        from orca_code.tools_dev import find_references
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return find_references(**kwargs)


class AnalyzeImageTool(Tool):
    name = "analyze_image"
    description = "Analyze image content"
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Image path"},
            "question": {"type": "string", "description": "Question"}
        }
    }
    required = ['image_path']
    risk_level = RiskLevel.EXEC

    def execute(self, image_path: str, question: str = None) -> str:
        from orca_code.tools_dev import analyze_image
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return analyze_image(**kwargs)


class CaptureCameraTool(Tool):
    name = "capture_camera"
    description = "Capture camera frame"
    parameters = {
        "type": "object",
        "properties": {
            "camera_index": {"type": "integer", "description": "Camera index"},
            "question": {"type": "string", "description": "Question"}
        }
    }
    required = []
    risk_level = RiskLevel.WRITE

    def execute(self, camera_index: str = None, question: str = None) -> str:
        from orca_code.tools_dev import capture_camera
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return capture_camera(**kwargs)


def register_dev_tools(registry) -> int:
    """Register all dev tools. Returns count of new registrations."""
    tools = [GitStatusTool(), GitDiffTool(), GitLogTool(), GitBlameTool(), GoToDefinitionTool(), FindReferencesTool(), AnalyzeImageTool(), CaptureCameraTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
