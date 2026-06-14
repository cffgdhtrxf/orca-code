"""orca_code.tools.base — Tool abstract base class and registry.

Each tool is a class that self-declares:
  - name: str           — unique tool identifier
  - description: str    — human-readable description for the model
  - parameters: dict    — JSON Schema for arguments
  - risk_level: RiskLevel — READ / WRITE / EXEC
  - required: list[str] — required parameter names

Usage:
    class ReadFileTool(Tool):
        name = "read_file"
        description = "Read a file from disk"
        parameters = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }
        required = ["path"]
        risk_level = RiskLevel.READ

        def execute(self, path: str) -> str:
            ...

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    schemas = registry.to_openai_schemas()
    result = registry.dispatch("read_file", {"path": "/tmp/test.txt"})
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from orca_code.permissions import RiskLevel


class Tool(ABC):
    """Abstract base class for all tools.

    Subclasses set class-level metadata and implement execute().
    """

    # ── Class-level metadata (override in subclasses) ──────────────────────
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    required: list[str] = []
    risk_level: RiskLevel = RiskLevel.EXEC  # safe default

    # ── Schema generation ──────────────────────────────────────────────────

    @classmethod
    def to_openai_schema(cls) -> dict[str, Any]:
        """Generate OpenAI-format function definition."""
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": {
                    **cls.parameters,
                    "required": cls.required,
                },
            },
        }

    # ── Validation ─────────────────────────────────────────────────────────

    @classmethod
    def validate_args(cls, args: dict[str, Any]) -> str | None:
        """Validate arguments against schema. Returns error string or None."""
        for key in cls.required:
            if key not in args or args[key] is None:
                return f"Missing required parameter: {key}"
        return None

    # ── Execution ──────────────────────────────────────────────────────────

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool. Subclasses override this."""
        ...

    def __call__(self, **kwargs) -> str:
        """Make tools callable like functions."""
        error = self.validate_args(kwargs)
        if error:
            return f"Error: {error}"
        return self.execute(**kwargs)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.name})>"


class ToolRegistry:
    """Manages tool registration, discovery, and dispatch.

    Supports both Tool subclasses and legacy plain functions.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._legacy: dict[str, Callable] = {}

    # ── Registration ───────────────────────────────────────────────────────

    def register(self, tool: Tool) -> None:
        """Register a Tool instance. Raises ValueError on duplicate."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def register_legacy(self, name: str, func: Callable) -> None:
        """Register a legacy flat function as a tool."""
        self._legacy[name] = func

    # ── Lookup ─────────────────────────────────────────────────────────────

    def get(self, name: str) -> Tool | None:
        """Get a registered Tool by name."""
        return self._tools.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._tools or name in self._legacy

    def __len__(self) -> int:
        return len(self._tools) + len(self._legacy)

    def list_names(self) -> list[str]:
        """Return all registered tool names."""
        return sorted(list(self._tools.keys()) + list(self._legacy.keys()))

    # ── Schema generation ──────────────────────────────────────────────────

    def to_openai_schemas(self) -> list[dict[str, Any]]:
        """Generate OpenAI-format function definitions for all tools."""
        schemas = [tool.to_openai_schema() for tool in self._tools.values()]
        # Legacy tools get minimal schemas
        for name in self._legacy:
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Legacy tool: {name}",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            })
        return schemas

    # ── Dispatch ───────────────────────────────────────────────────────────

    def dispatch(self, name: str, args: dict[str, Any] | None = None) -> str:
        """Execute a tool by name with optional arguments.

        Returns tool result string. Raises KeyError if not found.
        """
        args = args or {}

        if name in self._tools:
            tool = self._tools[name]
            return tool(**args)

        if name in self._legacy:
            sig = inspect.signature(self._legacy[name])
            valid = {k: v for k, v in args.items() if k in sig.parameters}
            return self._legacy[name](**valid)

        raise KeyError(f"Tool not found: {name}")

    # ── Bridge to legacy TOOL_MAP ──────────────────────────────────────────

    def to_legacy_map(self) -> dict[str, Callable]:
        """Convert to legacy flat dict: {name: callable}.
        Useful for bridging with the existing TOOL_MAP system.
        """
        result = {}
        for name, tool in self._tools.items():
            result[name] = tool  # Tool instances are callable
        result.update(self._legacy)
        return result
