"""orca_code.hooks — Pre/post tool execution hooks (P2-30).

Inspired by Claude Code's hook system and omp's rules/hooks.
Allows users to define callbacks that run before/after tool execution.

Hook types:
  - PreToolHook: runs BEFORE a tool executes. Can modify args or reject the call.
  - PostToolHook: runs AFTER a tool executes. Can transform the result.
  - PrePromptHook: runs BEFORE each LLM prompt. Can inject context.

Hooks are defined in config.json as:
  {
    "hooks": {
      "pre_tool": {
        "execute_command": "my_module.my_validator_func"
      },
      "post_tool": {
        "write_file": "my_module.my_logger_func"
      }
    }
  }

Built-in hooks:
  - log_all_tools: logs all tool calls to a file
  - validate_command: extra validation for shell commands
  - truncate_large_outputs: auto-truncate tool results > N chars
  - track_file_changes: maintain a list of modified files for rollback
"""

from __future__ import annotations

import importlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Hook types
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HookContext:
    """Context passed to all hooks."""
    tool_name: str
    args: dict
    session_id: str | None = None
    timestamp: float = field(default_factory=time.time)


PreToolHookFn = Callable[[HookContext], dict | None]
"""Pre-tool hook: receives context, returns modified args or None to reject.

Return None → allow the tool call with original args.
Return dict → allow with modified args.
Raise Exception → reject the tool call.
"""

PostToolHookFn = Callable[[HookContext, str], str]
"""Post-tool hook: receives context and result string, returns (possibly modified) result."""

# ═══════════════════════════════════════════════════════════════════════════════
# Hook registry
# ═══════════════════════════════════════════════════════════════════════════════

class HookRegistry:
    """Registry for pre/post tool hooks.

    Hooks can be:
      - Registered programmatically via register_pre / register_post
      - Loaded from config via load_from_config
    """

    def __init__(self):
        self._pre_hooks: dict[str, list[PreToolHookFn]] = defaultdict(list)
        self._post_hooks: dict[str, list[PostToolHookFn]] = defaultdict(list)
        # Wildcard hooks: run for ALL tools
        self._pre_wildcard: list[PreToolHookFn] = []
        self._post_wildcard: list[PostToolHookFn] = []

    def register_pre(self, tool_name: str, hook: PreToolHookFn):
        """Register a pre-tool hook for a specific tool (or '*' for all)."""
        if tool_name == "*":
            self._pre_wildcard.append(hook)
        else:
            self._pre_hooks[tool_name].append(hook)

    def register_post(self, tool_name: str, hook: PostToolHookFn):
        """Register a post-tool hook for a specific tool (or '*' for all)."""
        if tool_name == "*":
            self._post_wildcard.append(hook)
        else:
            self._post_hooks[tool_name].append(hook)

    def run_pre_hooks(self, ctx: HookContext) -> tuple[bool, dict]:
        """Run all pre-tool hooks for a tool.

        Returns:
            (allowed, modified_args)
            allowed=True → proceed with modified_args
            allowed=False → reject the call
        """
        args = dict(ctx.args)

        # Wildcard hooks first
        for hook in self._pre_wildcard:
            try:
                result = hook(ctx)
                if result is not None:
                    args.update(result)
            except Exception as e:
                return False, {"error": f"Pre-hook rejected: {e}"}

        # Tool-specific hooks
        for hook in self._pre_hooks.get(ctx.tool_name, []):
            try:
                result = hook(ctx)
                if result is not None:
                    args.update(result)
            except Exception as e:
                return False, {"error": f"Pre-hook '{ctx.tool_name}' rejected: {e}"}

        return True, args

    def run_post_hooks(self, ctx: HookContext, result: str) -> str:
        """Run all post-tool hooks for a tool. Returns (possibly modified) result."""
        modified = result

        # Wildcard hooks first
        for hook in self._post_wildcard:
            try:
                modified = hook(ctx, modified)
            except Exception:
                pass  # Post-hook failure should not break the tool result

        # Tool-specific hooks
        for hook in self._post_hooks.get(ctx.tool_name, []):
            try:
                modified = hook(ctx, modified)
            except Exception:
                pass

        return modified

    def load_from_config(self, config: dict):
        """Load hooks from configuration.

        Format:
          {"hooks": {"pre_tool": {"tool_name": "module.function", ...}, ...}}
        """
        hooks_config = config.get("hooks", {})
        if not hooks_config:
            return

        pre_config = hooks_config.get("pre_tool", {})
        for tool_name, func_path in pre_config.items():
            try:
                hook_fn = _resolve_function(func_path)
                self.register_pre(tool_name, hook_fn)
                logger.info("Registered pre-hook for %s: %s", tool_name, func_path)
            except Exception as e:
                logger.warning("Failed to load pre-hook %s: %s", func_path, e)

        post_config = hooks_config.get("post_tool", {})
        for tool_name, func_path in post_config.items():
            try:
                hook_fn = _resolve_function(func_path)
                self.register_post(tool_name, hook_fn)
                logger.info("Registered post-hook for %s: %s", tool_name, func_path)
            except Exception as e:
                logger.warning("Failed to load post-hook %s: %s", func_path, e)


def _resolve_function(func_path: str) -> Callable:
    """Resolve 'module.submodule.function' string to a callable."""
    parts = func_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid function path: {func_path}")

    module_path, func_name = parts
    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    if func is None:
        raise ValueError(f"Function '{func_name}' not found in {module_path}")
    if not callable(func):
        raise ValueError(f"'{func_path}' is not callable")
    return func


# ═══════════════════════════════════════════════════════════════════════════════
# Built-in hooks
# ═══════════════════════════════════════════════════════════════════════════════

def builtin_log_all_tools(ctx: HookContext) -> dict | None:
    """Built-in: log all tool calls to a JSONL file."""
    log_dir = Path.home() / ".orca" / "tool_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"tools_{time.strftime('%Y%m%d')}.jsonl"

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": ctx.tool_name,
        "args_keys": list(ctx.args.keys()),
        "session": ctx.session_id,
    }
    try:
        with open(log_file, "a", encoding="utf-8", errors="replace") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return None  # Allow the call


def builtin_track_file_changes(ctx: HookContext, result: str) -> str:
    """Built-in: track modified files for potential rollback."""
    if ctx.tool_name not in ("write_file", "edit_file", "apply_diff"):
        return result

    # Store path → previous content snapshot
    file_path = ctx.args.get("path", "")
    if not file_path:
        return result

    snapshot_dir = Path.home() / ".orca" / "file_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    p = Path(file_path)
    if p.exists():
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            snapshot_name = f"{p.name}.{int(time.time())}.bak"
            (snapshot_dir / snapshot_name).write_text(content, encoding="utf-8")
        except Exception:
            pass

    return result


def builtin_truncate_large_outputs(max_chars: int = 8000):
    """Built-in factory: truncate tool results to max_chars."""
    def truncate(ctx: HookContext, result: str) -> str:
        if len(result) > max_chars:
            truncated = result[:max_chars] + f"\n\n[输出被截断: {len(result):,} → {max_chars:,} 字符]"
            return truncated
        return result
    return truncate


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_hook_registry: HookRegistry | None = None


def get_hook_registry() -> HookRegistry:
    """Get or create the global hook registry singleton."""
    global _hook_registry
    if _hook_registry is None:
        _hook_registry = HookRegistry()
    return _hook_registry


def init_hooks(config: dict):
    """Initialize hooks from config at startup."""
    registry = get_hook_registry()

    # Load user-defined hooks from config
    registry.load_from_config(config)

    # Register built-in hooks (can be disabled by setting hooks.builtins: false)
    builtins_config = config.get("hooks", {}).get("builtins", {})
    if builtins_config.get("log_all_tools", True):
        registry.register_pre("*", builtin_log_all_tools)
    if builtins_config.get("track_file_changes", True):
        registry.register_post("*", builtin_track_file_changes)
    if builtins_config.get("truncate_large_outputs", True):
        max_chars = int(config.get("hooks", {}).get("max_output_chars", 8000))
        registry.register_post("*", builtin_truncate_large_outputs(max_chars))
