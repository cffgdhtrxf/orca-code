"""orca_code.cli.commands — CLI command handlers.

Extracted from config.py. These handlers bridge configuration and the CLI loop.
They are not part of the configuration layer — they consume config and interact
with the user via console I/O.
"""

from __future__ import annotations

import json

from orca_code.config import CONFIG, CONFIG_JSON, _get_mem_mgr, _sensitive_keys, console
from orca_code.infrastructure.config_loader import mask_key


def handle_config_cmd(user_input: str):
    """Handle /config command — view or modify configuration."""
    from rich.table import Table
    parts = user_input.strip().split(maxsplit=1)
    if len(parts) == 1 or "=" not in parts[1]:
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="dim"); t.add_column()
        for k, v in sorted(CONFIG.items()):
            if k.startswith("//"): continue
            val = str(v)
            if k in _sensitive_keys and val:
                val = mask_key(val)
            if len(val) > 80: val = val[:77] + "..."
            t.add_row(k, val)
        console.print(t)
        return
    key, _, value = parts[1].partition("=")
    key, value = key.strip(), value.strip()
    if not key: return
    if key in _sensitive_keys:
        console.print(f"[yellow]Use config.json to change {key}[/yellow]")
        return
    if value.lower() in ("true", "false"):
        value = value.lower() == "true"
    elif value.isdigit():
        value = int(value)
    CONFIG[key] = value
    try:
        CONFIG_JSON.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[green]{key} = {value} (saved, restart to apply)[/green]")
    except Exception as e:
        console.print(f"[red]Save failed: {e}[/red]")


def handle_profile_cmd(user_input: str):
    """Handle /profile command — view or modify user profile."""
    mgr = _get_mem_mgr()
    parts = user_input.strip().split(maxsplit=1)
    if mgr is None:
        console.print("[yellow]Memory system not enabled[/yellow]")
        return
    current = mgr.get_meta("user_profile") or ""
    if len(parts) == 1:
        console.print(); console.print("[bold]User Profile[/bold]")
        if current: console.print(f"  {current}")
        else: console.print("  [dim](empty)[/dim]")
        console.print()
        console.print("[dim]/profile add <content>  append[/dim]")
        console.print("[dim]/profile set <content>  overwrite[/dim]")
        console.print("[dim]/profile clear        clear[/dim]")
        return
    action = parts[1].strip()
    if action == "clear":
        mgr.set_meta("user_profile", "")
        console.print("[green]Profile cleared[/green]")
    elif action.startswith("set "):
        mgr.set_meta("user_profile", action[4:].strip()[:500])
        console.print("[green]Profile set[/green]")
    elif action.startswith("add "):
        new_profile = f"{current} {action[4:].strip()}".strip()[:500]
        mgr.set_meta("user_profile", new_profile)
        console.print("[green]Profile appended[/green]")
    else:
        mgr.set_meta("user_profile", action[:500])
        console.print("[green]Profile updated[/green]")
