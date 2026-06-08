"""orca_code.tools.bridge — Bridge between class-based Tool system and legacy TOOL_MAP.

Provides:
  - tool_registry: singleton ToolRegistry populated with core tools
  - sync_to_legacy(): copy registered tools into the legacy TOOL_MAP
  - sync_from_legacy(): import legacy flat functions into the registry

Usage (in main.py or tool_registry.py):
    from orca_code.tools.bridge import tool_registry, sync_to_legacy
    sync_to_legacy()  # adds class-based tools to TOOL_MAP
"""

from __future__ import annotations

from orca_code.tools.base import ToolRegistry
from orca_code.tools.core import register_core_tools

# Singleton registry
tool_registry = ToolRegistry()

# Register core tools eagerly
_core_count = register_core_tools(tool_registry)


def sync_to_legacy() -> int:
    """Copy all registered tools into the legacy TOOL_MAP.
    Returns number of tools synced.
    """
    from orca_code.tool_registry import TOOL_MAP
    count = 0
    for name, callable_fn in tool_registry.to_legacy_map().items():
        if name not in TOOL_MAP:
            TOOL_MAP[name] = callable_fn
            count += 1
    return count


def sync_from_legacy() -> int:
    """Import legacy TOOL_MAP functions into the registry.
    Returns number of tools imported.
    """
    from orca_code.tool_registry import TOOL_MAP
    count = 0
    for name, func in TOOL_MAP.items():
        if name not in tool_registry:
            tool_registry.register_legacy(name, func)
            count += 1
    return count


def get_registry() -> ToolRegistry:
    """Get the singleton ToolRegistry, auto-populated from legacy if empty."""
    if len(tool_registry) <= _core_count:
        sync_from_legacy()
    return tool_registry
