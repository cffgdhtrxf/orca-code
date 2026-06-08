"""orca_code.tools — Class-based tool system.

Provides:
  - Tool: abstract base class for all tools
  - ToolRegistry: registration, discovery, dispatch
  - tool_registry: singleton instance (populated from bridge)

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
from orca_code.tools.bridge import tool_registry, sync_to_legacy, sync_from_legacy

__all__ = ["Tool", "ToolRegistry", "tool_registry", "sync_to_legacy", "sync_from_legacy"]
