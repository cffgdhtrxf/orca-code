"""orca_code.tool_registry — Centralized tool definitions and function mapping.

TOOLS: List of OpenAI-format tool definitions (JSON schemas).
TOOL_MAP: Dict mapping tool names to callable functions.
run_tool(): Permission-checked tool dispatch.

Architecture:
  Root-level tools_*.py     — Canonical flat-function implementations (mature, stable).
  orca_code/tools/ package  — Class-based Tool wrappers (new, inherits from Tool base).
                               Each class delegates to root-level functions.

  tool_registry.py imports from root-level tools_*.py directly.
  The orca_code/tools/ package can be used via bridge.sync_from_legacy()
  to populate a class-based registry for future expansion.

This module breaks the circular dependency between main.py and its consumers
(session.py, tools_skills.py, subagent.py, tts_mcp.py). All imports from this
module are direct — no lazy-load workarounds needed.

For tool functions defined in main.py itself (update_profile, recall_conversation),
lazy tuple markers are used to avoid import loops with main.py.
"""

from __future__ import annotations

import inspect
from typing import Any

from orca_code.lsp import lsp_definition, lsp_diagnostics, lsp_references
from orca_code.subagent import agent_close, agent_eval, agent_open

# ─── Canonical tool imports (root-level modules — mature implementations) ─────
# These are the single source of truth for tool function implementations.
# The orca_code/tools/ package wraps these in class-based Tool subclasses.
from orca_code.tools_automation import (  # GUI + browser automation (7 tools)
    browser_click,
    browser_close,
    browser_open,
    browser_screenshot,
    browser_type,
    find_on_screen,
    gui_click,
    gui_hotkey,
    gui_move,
    gui_press,
    gui_type,
    window_focus,
)
from orca_code.tools_core import (  # Core file & command tools (9 tools)
    apply_diff,
    edit_file,
    execute_command,
    get_system_info,
    list_files,
    read_file,
    search_content,
    search_files,
    write_file,
)
from orca_code.tools_dev import (  # Dev tools: git, code nav, vision (8 tools)
    analyze_image,
    capture_camera,
    find_references,
    git_blame,
    git_diff,
    git_log,
    git_status,
    go_to_definition,
)
from orca_code.tools_office import (  # Office tools: Excel, Word, OCR (6 tools)
    ocr_image,
    read_excel,
    read_word,
    take_screenshot,
    write_excel,
    write_word,
)
from orca_code.tools_skills import (  # Skills & task scheduler (8 tools)
    add_task,
    create_skill,
    edit_skill,
    list_md_skills,
    list_skills,
    list_tasks,
    load_md_skill,
    load_skill,
    remove_task,
)
from orca_code.tools_web import (  # Web/search/weather tools (8 tools)
    get_location,
    get_weather,
    read_webpage,
    tavily_crawl,
    tavily_extract,
    tavily_map,
    web_fetch,
    web_search,
)
from orca_code.tools_memory import recall_conversation, update_profile
from orca_code.tts_mcp import speak_text

# ─── Optional: Coordinator ─────────────────────────────────────────────────
try:
    from orca_code.orchestrator import (
        coordinator_judge,
        coordinator_parallel,
        coordinator_pipeline,
    )
    HAS_COORDINATOR = True
except ImportError:
    HAS_COORDINATOR = False
    def coordinator_parallel(tasks_json, tools=""): return "Coordinator not available"
    def coordinator_pipeline(stages_json, tools=""): return "Coordinator not available"
    def coordinator_judge(task, n_solutions=3, tools=""): return "Coordinator not available"

# ─── Optional: Python REPL ───────────────────────────────────────────────────
try:
    from _python_repl import execute_python
    HAS_PYTHON_REPL = True
except ImportError:
    HAS_PYTHON_REPL = False
    def execute_python(code, timeout=30): return "REPL not available"


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS — OpenAI-format tool definitions (auto-generated from class registry)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_tools_schema() -> list[dict[str, Any]]:
    """Build TOOLS list from the ToolRegistry class-based system.

    Each tool in tools/*.py declares its own schema via Tool.parameters.
    This replaces the previous 900-line hardcoded TOOLS list, ensuring
    schemas are always in sync with implementations.
    """
    from orca_code.tools.base import ToolRegistry
    from orca_code.tools.core import register_core_tools
    from orca_code.tools.web import register_web_tools
    from orca_code.tools.office import register_office_tools
    from orca_code.tools.dev import register_dev_tools
    from orca_code.tools.skills import register_skills_tools
    from orca_code.tools.automation import register_automation_tools
    from orca_code.tools.browser import register_browser_tools
    from orca_code.tools.memory_tools import register_memory_tools
    from orca_code.tools.extended import register_extended_tools
    from orca_code.tools.tasks import register_tasks_tools

    registry = ToolRegistry()
    register_core_tools(registry)
    register_web_tools(registry)
    register_office_tools(registry)
    register_dev_tools(registry)
    register_skills_tools(registry)
    register_automation_tools(registry)
    register_browser_tools(registry)
    register_memory_tools(registry)
    register_extended_tools(registry)
    register_tasks_tools(registry)
    return registry.to_openai_schemas()

TOOL_MAP: dict[str, Any] = {
    # Core
    "execute_command": execute_command, "read_file": read_file,
    "write_file": write_file, "edit_file": edit_file, "apply_diff": apply_diff,
    "list_files": list_files,
    "search_files": search_files, "search_content": search_content,
    # Office
    "read_excel": read_excel, "write_excel": write_excel,
    "read_word": read_word, "write_word": write_word,
    "take_screenshot": take_screenshot, "ocr_image": ocr_image,
    # Web
    "web_fetch": web_fetch, "read_webpage": read_webpage,
    "get_weather": get_weather, "get_location": get_location,
    "web_search": web_search,
    "tavily_extract": tavily_extract, "tavily_crawl": tavily_crawl, "tavily_map": tavily_map,
    # Dev
    "git_status": git_status, "git_diff": git_diff,
    "git_log": git_log, "git_blame": git_blame,
    "go_to_definition": go_to_definition, "find_references": find_references,
    "analyze_image": analyze_image, "analyse_image": analyze_image, "capture_camera": capture_camera,
    # Skills
    "load_skill": load_skill, "create_skill": create_skill,
    "edit_skill": edit_skill, "list_skills": list_skills,
    "load_md_skill": load_md_skill, "list_md_skills": list_md_skills,
    # Tasks
    "add_task": add_task, "list_tasks": list_tasks,
    "remove_task": remove_task,
    # GUI
    "gui_click": gui_click, "gui_type": gui_type, "gui_move": gui_move,
    "gui_hotkey": gui_hotkey, "gui_press": gui_press,
    "window_focus": window_focus, "find_on_screen": find_on_screen,
    # Browser
    "browser_open": browser_open, "browser_click": browser_click,
    "browser_type": browser_type, "browser_screenshot": browser_screenshot,
    "browser_close": browser_close,
    # System
    "get_system_info": get_system_info,
    # TTS
    "speak_text": speak_text,
    # REPL
    "execute_python": execute_python,
    # Sub-agents
    "agent_open": agent_open, "agent_eval": agent_eval, "agent_close": agent_close,
    # Coordinator (multi-agent orchestration)
    "coordinator_parallel": coordinator_parallel,
    "coordinator_pipeline": coordinator_pipeline,
    "coordinator_judge": coordinator_judge,
    # Memory & Profile
    "recall_conversation": recall_conversation,
    "update_profile": update_profile,
    # LSP
    "lsp_diagnostics": lsp_diagnostics,
    "lsp_references": lsp_references,
    "lsp_definition": lsp_definition,
}

# Build TOOLS schema from class registry, then add extra entries from TOOL_MAP
# that aren't yet in the class-based system.
TOOLS: list[dict[str, Any]] = _build_tools_schema()
_existing_tool_names = {t["function"]["name"] for t in TOOLS}
for _name, _func in TOOL_MAP.items():
    if _name not in _existing_tool_names:
        TOOLS.append({
            "type": "function",
            "function": {
                "name": _name,
                "description": getattr(_func, "__doc__", "") or f"Tool: {_name}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        })

def run_tool(name: str, args: dict) -> str:
    """Permission-checked tool dispatch. All tool calls flow through here.

    Supports caching for expensive tools (web_search, read_webpage, etc.)
    and large-output storage via ContentStore.
    """
    func = TOOL_MAP.get(name)
    if func is None:
        # Check MCP tools
        mcp_result = _try_mcp_tool(name, args)
        if mcp_result is not None:
            return mcp_result
        return f"Error: unknown tool - {name}"

    # Permission check (Claude Code style) — with WS delegation (P0)
    from orca_code.config import PERMISSION_MODE, PERMISSION_RULES
    from orca_code.permissions import (
        resolve_permission,
    )
    if not resolve_permission(name, args, PERMISSION_MODE, PERMISSION_RULES):
        return f"Permission denied for '{name}'. Use /permissions to manage rules."

    sig = inspect.signature(func)
    valid = {k: v for k, v in args.items() if k in sig.parameters}

    # ── P2-33: Validate arguments against schema ──────────────────────────
    from orca_code.tool_validator import validate_with_suggestion
    validation_error = validate_with_suggestion(name, valid)
    if validation_error:
        return validation_error

    # ── P2-30: Run pre-tool hooks ────────────────────────────────────────
    try:
        from orca_code.hooks import HookContext, get_hook_registry
        hook_registry = get_hook_registry()
        ctx = HookContext(tool_name=name, args=valid)
        allowed, modified_args = hook_registry.run_pre_hooks(ctx)
        if not allowed:
            return f"工具 '{name}' 被钩子拦截: {modified_args.get('error', '未知原因')}"
        if modified_args != valid:
            valid = modified_args
    except ImportError:
        pass  # Hooks module not available

    # ── P2-32: File snapshot before modification ──────────────────────────
    file_path = valid.get("path", "")
    snapshot_path = None
    if name in ("write_file", "edit_file", "apply_diff") and file_path:
        try:
            from orca_code.rollback import get_file_tracker
            tracker = get_file_tracker()
            snapshot_path = tracker.snapshot(file_path)
        except ImportError:
            pass

    # Try cache for cacheable tools
    from orca_code.tool_cache import CACHEABLE_TOOLS, cached_tool_call
    if name in CACHEABLE_TOOLS:
        result = cached_tool_call(name, func, **valid)
    else:
        result = func(**valid)

    # ── P2-32: Record file change for rollback ────────────────────────────
    if name in ("write_file", "edit_file", "apply_diff") and file_path:
        try:
            from orca_code.rollback import get_file_tracker
            tracker = get_file_tracker()
            tracker.record_change(file_path, name, snapshot_path)
        except ImportError:
            pass

    # ── P2-30: Run post-tool hooks ───────────────────────────────────────
    try:
        from orca_code.hooks import get_hook_registry
        hook_registry = get_hook_registry()
        ctx2 = HookContext(tool_name=name, args=valid)
        result = hook_registry.run_post_hooks(ctx2, str(result))
    except ImportError:
        pass

    # Large output: truncate with note. read_file gets higher limit (100K)
    # because users frequently analyze large source files.
    _limit = 100000 if name == "read_file" else 8000
    if isinstance(result, str) and len(result) > _limit:
        result = result[: _limit] + f"\n\n[输出被截断: {len(result):,} 字符 → {_limit:,} 字符]"

    # Constitution Article IV: verification markers
    from orca_code.constitution import verification_marker
    if isinstance(result, str):
        is_error = result.startswith("Error") or result.startswith("错误") or result.startswith("Permission denied")
        if is_error:
            result += verification_marker(False, "")
        elif name in ("write_file", "edit_file", "apply_diff") or name in ("execute_command", "execute_python"):
            result += verification_marker(True, f"tool={name}")

    return result


def _try_mcp_tool(name: str, args: dict) -> str | None:
    """Try to dispatch a tool call to an MCP server.

    Supports two naming formats:
      - New: mcp__<server_name>__<tool_name>  (double underscore)
      - Old: mcp_<server_name>_<tool_name>     (single underscore)
    """
    if not (name.startswith("mcp__") or name.startswith("mcp_")):
        return None
    try:
        from orca_code.mcp_client import get_mcp_registry
        registry = get_mcp_registry()
        if name.startswith("mcp__"):
            parts = name.split("__", 2)
            if len(parts) < 3:
                return f"Error: invalid MCP tool name format: {name}"
            server_name = parts[1]
            tool_name = parts[2]
        else:
            inner = name[4:]
            sep = inner.find("_")
            if sep == -1:
                return f"Error: invalid MCP tool name format: {name}"
            server_name = inner[:sep]
            tool_name = inner[sep + 1:]
        return registry.call_tool(server_name, tool_name, args)
    except Exception as e:
        return f"Error: MCP tool '{name}' failed: {e}"
