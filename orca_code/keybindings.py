"""orca_code.keybindings — Configurable keyboard shortcuts (P2-44).

Reads keybindings from ~/.orca/keybindings.json.
Falls back to hardcoded defaults if file is missing.

Default bindings:
  Ctrl+C    — interrupt generation (or exit if idle)
  Ctrl+R    — history search
  Ctrl+P/N  — history navigation
  PageUp    — scroll up
  PageDown  — scroll down
  Home      — scroll to bottom
  Escape    — clear input
  Enter     — send message

Config format (~/.orca/keybindings.json):
  {
    "submit": "return",
    "interrupt": "ctrl+c",
    "history_search": "ctrl+r",
    "history_prev": "ctrl+p",
    "history_next": "ctrl+n",
    "scroll_up": "pageup",
    "scroll_down": "pagedown",
    "scroll_bottom": "home",
    "clear_input": "escape",
    "exit": "ctrl+d"
  }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_BINDINGS: dict[str, str] = {
    "submit": "return",
    "interrupt": "ctrl+c",
    "history_search": "ctrl+r",
    "history_prev": "ctrl+p",
    "history_next": "ctrl+n",
    "scroll_up": "pageup",
    "scroll_down": "pagedown",
    "scroll_bottom": "home",
    "clear_input": "escape",
    "exit": "ctrl+d",
    "force_exit": "ctrl+c",  # when idle
}

ACTION_LABELS: dict[str, str] = {
    "submit": "发送消息",
    "interrupt": "中断生成",
    "history_search": "搜索历史",
    "history_prev": "上一条历史",
    "history_next": "下一条历史",
    "scroll_up": "向上滚动",
    "scroll_down": "向下滚动",
    "scroll_bottom": "滚动到底部",
    "clear_input": "清除输入",
    "exit": "退出",
    "force_exit": "强制退出",
}


def load_keybindings(config_path: Path | None = None) -> dict[str, str]:
    """Load keybindings from config file, falling back to defaults.

    Args:
        config_path: Path to keybindings.json. Default: ~/.orca/keybindings.json

    Returns:
        Dict mapping action names to key strings.
    """
    if config_path is None:
        config_path = Path.home() / ".orca" / "keybindings.json"

    bindings = dict(DEFAULT_BINDINGS)

    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if key in DEFAULT_BINDINGS and isinstance(value, str):
                        bindings[key] = value
        except Exception:
            pass  # Use defaults on any error

    return bindings


def save_default_keybindings(config_path: Path | None = None):
    """Write the default keybindings to a config file (if it doesn't exist)."""
    if config_path is None:
        config_path = Path.home() / ".orca" / "keybindings.json"

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(DEFAULT_BINDINGS, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def get_binding_help() -> str:
    """Get a formatted help string showing current bindings."""
    bindings = load_keybindings()
    lines = ["快捷键配置:"]
    for action, key in bindings.items():
        label = ACTION_LABELS.get(action, action)
        lines.append(f"  {key:12s} — {label}")
    return "\n".join(lines)
