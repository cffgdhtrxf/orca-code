"""orca_code.plugin_loader — External plugin/extension system (P2-37).

Loads external tool modules from a plugins/ directory.
Each plugin is a Python file or package with a register() function.

Plugin format (plugin file: plugins/my_plugin.py):
    def register(tool_registry, hook_registry):
        '''Called on startup. Register tools and hooks.'''

        def my_tool(arg1: str) -> str:
            return f"Result: {arg1}"

        tool_registry["my_tool"] = my_tool
        # Optionally register hooks
        # hook_registry.register_pre("execute_command", my_validator)

Also supports registering tool schemas for the OpenAI API format.

Usage:
    from orca_code.plugin_loader import load_plugins
    loaded = load_plugins()
    for name, info in loaded.items():
        print(f"Loaded: {name} — {info.get('description', '')}")
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def discover_plugins(plugins_dir: Path | None = None) -> list[Path]:
    """Discover plugin files in the plugins directory.

    Scans for:
      - Single-file plugins: plugins/my_tool.py
      - Package plugins: plugins/my_tool/__init__.py
      - Config-based plugins: plugins/my_tool/plugin.json

    Args:
        plugins_dir: Directory to scan. Default: <script_dir>/plugins/

    Returns:
        List of plugin entry point paths.
    """
    if plugins_dir is None:
        from orca_code.config import SCRIPT_DIR
        plugins_dir = SCRIPT_DIR / "plugins"

    plugins_dir = Path(plugins_dir)
    if not plugins_dir.exists():
        return []

    discovered: list[Path] = []

    for entry in sorted(plugins_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".py" and not entry.name.startswith("_"):
            discovered.append(entry)
        elif entry.is_dir() and not entry.name.startswith("_"):
            init_file = entry / "__init__.py"
            if init_file.exists():
                discovered.append(init_file)
            plugin_json = entry / "plugin.json"
            if plugin_json.exists():
                discovered.append(plugin_json)

    return discovered


def load_plugin(plugin_path: Path) -> dict[str, Any]:
    """Load a single plugin and return its registration info.

    Args:
        plugin_path: Path to the plugin file or package __init__.py.

    Returns:
        Dict with plugin metadata: {name, description, version, tools, hooks}
    """
    result: dict[str, Any] = {
        "name": plugin_path.stem if plugin_path.stem != "__init__" else plugin_path.parent.name,
        "path": str(plugin_path),
        "tools": [],
        "hooks": 0,
        "loaded": False,
        "error": None,
    }

    try:
        # Check for plugin.json metadata
        meta_path = plugin_path.parent / "plugin.json" if plugin_path.stem == "__init__" else None
        if meta_path and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                result["name"] = meta.get("name", result["name"])
                result["description"] = meta.get("description", "")
                result["version"] = meta.get("version", "0.1.0")
            except Exception:
                pass

        # Load the module
        module_name = f"orca_plugin_{result['name'].replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, str(plugin_path))
        if spec is None or spec.loader is None:
            result["error"] = f"Cannot load module spec for {plugin_path}"
            return result

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Call register() if present
        if hasattr(module, "register"):
            new_tools: dict = {}
            new_hooks: int = 0

            def tool_registry_add(name: str, fn=None, schema: dict | None = None):
                """Callback for plugins to register tools."""
                if fn is not None:
                    new_tools[name] = fn
                result["tools"].append(name)
                # If schema provided, could register in TOOLS schema list
                if schema:
                    result.setdefault("schemas", {})[name] = schema

            def hook_registry_add(kind: str, tool_name: str, fn):
                """Callback for plugins to register hooks."""
                nonlocal new_hooks
                new_hooks += 1
                try:
                    from orca_code.hooks import get_hook_registry
                    reg = get_hook_registry()
                    if kind == "pre":
                        reg.register_pre(tool_name, fn)
                    elif kind == "post":
                        reg.register_post(tool_name, fn)
                except ImportError:
                    pass

            # Call the plugin's register function
            module.register(tool_registry_add, hook_registry_add)
            result["hooks"] = new_hooks

            # Register tools from plugin
            for tool_name, tool_fn in new_tools.items():
                from orca_code.tool_registry import TOOL_MAP
                TOOL_MAP[tool_name] = tool_fn
                logger.info("Plugin '%s' registered tool: %s", result["name"], tool_name)

        result["loaded"] = True

    except Exception as e:
        result["error"] = str(e)
        logger.error("Failed to load plugin %s: %s", plugin_path, e)

    return result


def load_plugins(plugins_dir: Path | None = None) -> dict[str, dict]:
    """Discover and load all plugins.

    Args:
        plugins_dir: Directory to scan for plugins.

    Returns:
        Dict mapping plugin names to their load results.
    """
    discovered = discover_plugins(plugins_dir)
    if not discovered:
        return {}

    results: dict[str, dict] = {}
    for plugin_path in discovered:
        info = load_plugin(plugin_path)
        results[info["name"]] = info

    loaded_count = sum(1 for r in results.values() if r["loaded"])
    tool_count = sum(len(r.get("tools", [])) for r in results.values())
    logger.info("Plugins: %d/%d loaded (%d tools)", loaded_count, len(results), tool_count)

    return results


def reload_plugins(plugins_dir: Path | None = None) -> dict[str, dict]:
    """Reload all plugins (useful after editing plugin code)."""
    # Clear previously loaded plugin modules from sys.modules
    to_remove = [k for k in sys.modules if k.startswith("orca_plugin_")]
    for k in to_remove:
        del sys.modules[k]

    return load_plugins(plugins_dir)
