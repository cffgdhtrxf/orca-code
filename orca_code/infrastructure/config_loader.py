"""orca_code.infrastructure.config_loader — Pure configuration loading with zero side effects.

Extracted from config.py. This module ONLY loads configuration from files.
It does NOT:
  - Initialize the console (that's platform.py)
  - Detect optional dependencies (that's in config.py)
  - Create OpenAI clients (that's in provider_client.py)
  - Initialize memory/permission systems

Importing this module is <10ms and has zero side effects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# ─── Default configuration ───────────────────────────────────────────────────

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model_name": "deepseek-chat",
    "max_output_tokens": 8192,
    "enable_think_mode": True,
    "silent_cmd": True,
    "tavily_api_key": "",
    "user_city": "",
    "auto_install_deps": True,
    "enable_gui_auto": False,
    "enable_browser_auto": False,
    "context_max_tokens": 100000,
    "preferred_shell": "",
    "max_workers": 5,
    "keep_last_rounds": 20,
    "persona": "",
    "cmd_timeout": 120,
    "reasoning_effort": "high",
    "enable_tts": True,
    "enable_voice": True,
    "vision_model": "",
    "vision_base_url": "",
    "vision_api_key": "",
    "local_model": False,
    "memory_model": "",
    "memory_api_key": "",
    "memory_base_url": "",
    # Permission system
    "permission_mode": "auto",
    "permission_rules": {},
}

# ─── TXT compatibility mapping ───────────────────────────────────────────────

_TXT_KEY_MAP = {
    "API_KEY": "api_key",
    "BASE_URL": "base_url",
    "MODEL": "model_name",
    "TAVILY_API_KEY": "tavily_api_key",
    "THINKING_ENABLED": "enable_think_mode",
    "REASONING_EFFORT": "reasoning_effort",
    "MAX_OUTPUT_TOKENS": "max_output_tokens",
    "KEEP_BLOCKS": "keep_blocks",
    "MAX_WORKERS": "max_workers",
    "PERSONA": "persona",
    "CMD_TIMEOUT": "cmd_timeout",
}

_INT_KEYS = (
    "max_output_tokens", "context_max_tokens", "max_workers",
    "keep_last_rounds", "keep_blocks", "cmd_timeout",
)

_BOOL_KEYS = (
    "enable_think_mode", "silent_cmd", "auto_install_deps",
    "enable_gui_auto", "enable_browser_auto", "enable_tts",
    "enable_voice", "local_model",
)


# ─── Loading functions ───────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    """Load config from JSON file. Returns empty dict if not found."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_txt(path: Path) -> dict:
    """Load config from legacy TXT file. Returns empty dict if not found."""
    if not path.exists():
        return {}
    cfg: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            mapped = _TXT_KEY_MAP.get(k, k.lower())
            cfg[mapped] = v

    # Type coercion (TXT values are always strings)
    for k in _INT_KEYS:
        if k in cfg:
            try:
                v_int = int(cfg[k])
                if v_int > 0 or k == "keep_blocks":
                    cfg[k] = v_int
                else:
                    del cfg[k]
            except (ValueError, TypeError):
                del cfg[k]
    for k in _BOOL_KEYS:
        if k in cfg:
            cfg[k] = str(cfg[k]).lower() in ("true", "1", "yes")
    return cfg


def load_config(
    config_json: Path | None = None,
    config_txt: Path | None = None,
    script_dir: Path | None = None,
) -> dict:
    """Load configuration, merging JSON > TXT > defaults.

    Args:
        config_json: Path to config.json. Auto-detected if None.
        config_txt: Path to legacy 配置文件.txt. Auto-detected if None.
        script_dir: Root directory. Auto-detected if None.

    Returns:
        Merged config dict. Never returns incomplete — always fills gaps
        from DEFAULT_CONFIG.
    """
    if script_dir is None:
        script_dir = Path(__file__).parent.parent.parent.resolve()
    if config_json is None:
        config_json = script_dir / "config.json"
    if config_txt is None:
        config_txt = script_dir / "配置文件.txt"

    cfg = dict(DEFAULT_CONFIG)

    if config_json.exists():
        user = _load_json(config_json)
        cfg.update(user)
        return cfg

    if config_txt.exists():
        user = _load_txt(config_txt)
        cfg.update(user)
        return cfg

    # Neither exists: create default JSON template
    config_json.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cfg


# Backward compat alias
_load_txt_config = _load_txt


def mask_key(key: str) -> str:
    """Mask an API key for safe display: 'sk-ab...xyz'."""
    if not key or len(key) < 10:
        return "***"
    return key[:5] + "***" + key[-3:]
