"""Orca Code — desktop AI assistant.

Backward-compatible package. All legacy names available at orca_code.* level
via lazy loading — imports are deferred until first access, making `import orca_code`
nearly instant.

For new code, import directly from submodules:
    from orca_code.config import CONFIG
    from orca_code.tools_core import execute_command

New in v5.1:
    from orca_code.core.errors import classify_error
    from orca_code.providers import get_adapter
    from orca_code.tools import tool_registry, Tool
    from orca_code.infrastructure import FeatureFlags
"""

from __future__ import annotations

__version__ = "5.1.0"
__author__ = "Orca Code Contributors"
__license__ = "MIT"

import importlib
import sys
from typing import Any

# ─── Lazy import registry ────────────────────────────────────────────────────
# Each entry maps a submodule to its fully-qualified import path.
# When any name from a submodule is accessed, the module is imported once
# and all its public names are cached in this module's __dict__.

_LAZY_MODULES: dict[str, str] = {
    "config":           "orca_code.config",
    "utils":            "orca_code.utils",
    "security":         "orca_code.security",
    "tools_core":       "orca_code.tools_core",
    "tools_office":     "orca_code.tools_office",
    "tools_web":        "orca_code.tools_web",
    "tools_dev":        "orca_code.tools_dev",
    "tools_skills":     "orca_code.tools_skills",
    "tools_automation": "orca_code.tools_automation",
    "tts_mcp":          "orca_code.tts_mcp",
    "session":          "orca_code.session",
    "main":             "orca_code.main",
    "config_loader":    "orca_code.infrastructure.config_loader",
}

# Track which modules have been eagerly loaded
_loaded_modules: dict[str, Any] = {}

# Known public names from each module (populated on first access)
_name_cache: dict[str, str] = {}  # name → module_key


def __getattr__(name: str) -> Any:
    """Lazy-load public names from submodules on first access.

    When `orca_code.execute_command` is accessed:
    1. Search all registered submodules for 'execute_command'
    2. Import the module, cache all its public names
    3. Return the requested attribute

    This makes `import orca_code` O(1) instead of O(all modules).
    """
    # Avoid recursion for dunder names
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)

    # Check name cache first
    if name in _name_cache:
        module_key = _name_cache[name]
        module = _loaded_modules.get(module_key)
        if module is None:
            module = importlib.import_module(_LAZY_MODULES[module_key])
            _loaded_modules[module_key] = module
        attr = getattr(module, name)
        globals()[name] = attr
        return attr

    # Search all lazy modules for the name
    for module_key, module_path in _LAZY_MODULES.items():
        module = _loaded_modules.get(module_key)
        if module is None:
            try:
                module = importlib.import_module(module_path)
                _loaded_modules[module_key] = module
            except ImportError:
                continue

        if hasattr(module, name):
            # Cache this name→module mapping
            _name_cache[name] = module_key
            # Cache the attribute
            attr = getattr(module, name)
            globals()[name] = attr
            return attr

    raise AttributeError(
        f"module 'orca_code' has no attribute '{name}'"
    )


def __dir__() -> list[str]:
    """Return all discoverable names for tab completion."""
    base = list(globals().keys())
    # Add known names from already-loaded modules
    for module in _loaded_modules.values():
        base.extend(dir(module))
    return sorted(set(base))
