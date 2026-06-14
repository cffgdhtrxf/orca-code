"""orca_code.alias_store — Persistent command aliases (P2-96).

Save/load aliases from ~/.orca/aliases.json.
Aliases are command shortcuts: "ll" -> "list_files /home"
"""
from __future__ import annotations
import json
from pathlib import Path

def _path() -> Path:
    return Path.home() / ".orca" / "aliases.json"

def load_aliases() -> dict[str, str]:
    p = _path()
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except: pass
    return {}

def save_aliases(aliases: dict[str, str]):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(aliases, ensure_ascii=False, indent=2))

def add_alias(name: str, command: str) -> dict[str, str]:
    aliases = load_aliases()
    aliases[name] = command
    save_aliases(aliases)
    return aliases

def remove_alias(name: str) -> dict[str, str]:
    aliases = load_aliases()
    aliases.pop(name, None)
    save_aliases(aliases)
    return aliases
