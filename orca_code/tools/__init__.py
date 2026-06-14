"""orca_code.tools — Class-based tool system (forward-looking API).

Architecture:
  Root-level tools_*.py       — Canonical implementations (flat functions).
                                 Mature, stable. All tool_registry.py imports come from here.
  orca_code/tools/*.py        — Tool subclasses wrapping root-level functions.
                                 Each class provides typed parameters, validation,
                                 and structured output. Useful for future expansion.
  orca_code/tools/bridge.py   — sync_from_legacy() / sync_to_legacy() bridge between
                                 the class-based registry and the legacy TOOL_MAP dict.

Usage:
    from orca_code.tools import tool_registry
    tool_registry.sync_from_legacy()   # populate from TOOLS + TOOL_MAP
    tool = tool_registry.get("read_file")
    result = tool.execute(path="/foo/bar.txt")

Provides:
  - Tool: abstract base class with name, description, parameters, risk_level, execute()
  - ToolRegistry: registration, discovery, dispatch, schema generation
  - tool_registry: singleton instance (populated via bridge)

Submodules (one per tool category):
  - core.py        — read, write, edit, list, search, exec, system info (9)
  - web.py         — fetch, search, weather, location (5)
  - office.py      — Excel, Word, screenshot, OCR (6)
  - dev.py         — Git, code nav, vision, camera (8)
  - skills.py      — Skill management (6)
  - tasks.py       — Scheduled tasks (3)
  - automation.py  — GUI automation (7)
  - browser.py     — Browser automation (5)
  - extended.py    — TTS, sub-agents, REPL, LSP (8)

Total: 57 class-based tools + bridge to legacy TOOL_MAP.
"""

from orca_code.tools.base import Tool, ToolRegistry
from orca_code.tools.bridge import sync_from_legacy, sync_to_legacy, tool_registry

__all__ = ["Tool", "ToolRegistry", "tool_registry", "sync_to_legacy", "sync_from_legacy"]
