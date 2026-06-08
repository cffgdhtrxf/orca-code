"""orca_code.tools.bridge — Bridge between class-based Tool system and legacy TOOL_MAP.

Provides:
  - tool_registry: singleton ToolRegistry populated with ALL class-based tools
  - sync_to_legacy(): copy registered tools into the legacy TOOL_MAP
  - sync_from_legacy(): import legacy flat functions into the registry
"""

from __future__ import annotations

from orca_code.tools.base import ToolRegistry

# Singleton registry
tool_registry = ToolRegistry()

# Register all class-based tools eagerly
_registration_counts = {}

def _register_all():
    """Register all tool categories. Idempotent."""
    from orca_code.tools.core import register_core_tools
    from orca_code.tools.web import register_web_tools
    from orca_code.tools.office import register_office_tools
    from orca_code.tools.dev import register_dev_tools
    from orca_code.tools.skills import register_skills_tools
    from orca_code.tools.tasks import register_tasks_tools
    from orca_code.tools.automation import register_automation_tools
    from orca_code.tools.browser import register_browser_tools
    from orca_code.tools.extended import register_extended_tools

    for name, fn in [
        ("core", register_core_tools),
        ("web", register_web_tools),
        ("office", register_office_tools),
        ("dev", register_dev_tools),
        ("skills", register_skills_tools),
        ("tasks", register_tasks_tools),
        ("automation", register_automation_tools),
        ("browser", register_browser_tools),
        ("extended", register_extended_tools),
    ]:
        if name not in _registration_counts:
            _registration_counts[name] = fn(tool_registry)

_register_all()


def sync_to_legacy() -> int:
    """Copy all registered tools into the legacy TOOL_MAP. Returns count synced."""
    from orca_code.tool_registry import TOOL_MAP
    count = 0
    for name, callable_fn in tool_registry.to_legacy_map().items():
        if name not in TOOL_MAP:
            TOOL_MAP[name] = callable_fn
            count += 1
    return count


def sync_from_legacy() -> int:
    """Import legacy TOOL_MAP functions into the registry. Returns count imported."""
    from orca_code.tool_registry import TOOL_MAP
    count = 0
    for name, func in TOOL_MAP.items():
        if name not in tool_registry:
            tool_registry.register_legacy(name, func)
            count += 1
    return count


def get_registry() -> ToolRegistry:
    """Get the singleton ToolRegistry, auto-populated from legacy if needed."""
    if len(tool_registry) < 50:
        sync_from_legacy()
    return tool_registry
