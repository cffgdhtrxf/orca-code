"""orca_code.tools — Class-based tool system.

Provides:
  - Tool: abstract base class for all tools
  - ToolRegistry: registration, discovery, dispatch
  - tool_registry: singleton instance (populated from bridge)

Bridge to legacy system:
  from orca_code.tools.bridge import sync_to_legacy, sync_from_legacy

Usage:
  from orca_code.tools import Tool, ToolRegistry, tool_registry
"""

from orca_code.tools.base import Tool, ToolRegistry
from orca_code.tools.bridge import tool_registry, sync_to_legacy, sync_from_legacy

__all__ = ["Tool", "ToolRegistry", "tool_registry", "sync_to_legacy", "sync_from_legacy"]
