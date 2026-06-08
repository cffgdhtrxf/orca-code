"""orca_code.config — Configuration globals and lazy client initialization.

Thin compatibility layer. Pure config loading is in infrastructure/config_loader.
Expensive globals (client, mem_mgr) are created lazily on first access.

Importing this module is now fast — no OpenAI client created at import time.
"""

from __future__ import annotations

import os
import sys
import json
import platform
import logging
from pathlib import Path
from typing import Any, Dict

# ─── Pure config loading (from config_loader) ────────────────────────────────
from orca_code.infrastructure.config_loader import (
    DEFAULT_CONFIG, load_config, mask_key,
)

# Console (lightweight — Rich console creation is cheap)
from rich.console import Console
console = Console()

# ─── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.parent.resolve()
CONFIG_JSON = SCRIPT_DIR / "config.json"
CONFIG_TXT = SCRIPT_DIR / "配置文件.txt"
SAVE_DIR = SCRIPT_DIR / "save"
TEMP_DIR = SCRIPT_DIR / "temp"
SKILLS_DIR = SCRIPT_DIR / "skills"
OUTPUT_DIR = SCRIPT_DIR / "output"
LOGS_DIR = SCRIPT_DIR / "logs"
MODELS_DIR = SCRIPT_DIR / "models"
WORKING_DIR = Path.cwd()

# Ensure directories exist
for d in (SAVE_DIR, TEMP_DIR, SKILLS_DIR, OUTPUT_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ─── Load config ─────────────────────────────────────────────────────────────
CONFIG = load_config(CONFIG_JSON, SCRIPT_DIR / "配置文件.txt", SCRIPT_DIR)

# ─── Simple globals (extracted immediately — fast) ───────────────────────────
API_KEY: str = CONFIG["api_key"]
BASE_URL: str = CONFIG["base_url"]
MODEL: str = CONFIG["model_name"]
MAX_OUTPUT_TOKENS: int = int(CONFIG["max_output_tokens"])
ENABLE_THINK_MODE: bool = str(CONFIG["enable_think_mode"]).lower() == "true"
SILENT_CMD: bool = str(CONFIG["silent_cmd"]).lower() == "true"
TAVILY_API_KEY: str = CONFIG["tavily_api_key"]
USER_CITY: str = CONFIG["user_city"]
AUTO_INSTALL_DEPS: bool = str(CONFIG["auto_install_deps"]).lower() == "true"
ENABLE_GUI_AUTO: bool = str(CONFIG["enable_gui_auto"]).lower() == "true"
ENABLE_BROWSER_AUTO: bool = str(CONFIG["enable_browser_auto"]).lower() == "true"
CONTEXT_MAX_TOKENS: int = int(CONFIG["context_max_tokens"])
PREFERRED_SHELL: str = CONFIG["preferred_shell"]
MAX_WORKERS: int = int(CONFIG["max_workers"])
KEEP_ROUNDS: int = int(CONFIG.get("keep_last_rounds", CONFIG.get("keep_blocks", 20)))
PERSONA: str = CONFIG["persona"]
CMD_TIMEOUT: int = int(CONFIG["cmd_timeout"])
REASONING_EFFORT: str = CONFIG["reasoning_effort"] if CONFIG["reasoning_effort"] in ("high", "max") else "high"
ENABLE_TTS: bool = str(CONFIG.get("enable_tts", True)).lower() == "true"
ENABLE_VOICE: bool = str(CONFIG.get("enable_voice", True)).lower() == "true"
VISION_MODEL: str = CONFIG.get("vision_model", "")
VISION_BASE_URL: str = CONFIG.get("vision_base_url", "") or BASE_URL
VISION_API_KEY: str = CONFIG.get("vision_api_key", "") or API_KEY

# Model family flags
IS_DEEPSEEK: bool = "deepseek" in MODEL.lower() or "deepseek" in BASE_URL.lower()
IS_LOCAL: bool = str(CONFIG.get("local_model", False)).lower() == "true" or any(
    host in BASE_URL.lower() for host in ("localhost", "127.0.0.1", "192.168", "10.", "172.16", "0.0.0.0")
)
IS_GEMMA: bool = "gemma" in MODEL.lower()
IS_QWEN: bool = "qwen" in MODEL.lower()
IS_MINISTRAL: bool = any(kw in MODEL.lower() for kw in ("mistral", "ministral"))
USE_SIMPLE_PROMPT: bool = IS_GEMMA or IS_QWEN or IS_MINISTRAL

# Multimodal detection
_MULTIMODAL_PATTERNS = ['vl', 'vision', 'gpt-4o', 'gpt-4-turbo', 'gemini',
                        'claude', 'gemma', 'llava', 'minicpm', 'internvl',
                        'qwen2.5-vl', 'qwen-vl', 'pixtral', 'phi-3-vision']
if "multimodal" in CONFIG:
    IS_MULTIMODAL: bool = str(CONFIG.get("multimodal", False)).lower() == "true"
else:
    IS_MULTIMODAL: bool = any(p in MODEL.lower() for p in _MULTIMODAL_PATTERNS)

# Terminal width
try:
    TERM_WIDTH = os.get_terminal_size().columns
except Exception:
    TERM_WIDTH = 80

# Permission
from orca_code.permissions import PermissionMode
PERMISSION_MODE = PermissionMode(CONFIG.get("permission_mode", "auto"))
PERMISSION_RULES: Dict[str, str] = CONFIG.get("permission_rules", {})

# ─── Optional dependency detection (fast try/except at module level) ─────────

try:
    from PIL import ImageGrab
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

if sys.platform == "win32":
    try:
        import win32com.client
        HAS_TTS = True
    except ImportError:
        HAS_TTS = False
else:
    HAS_TTS = False

try:
    import torch
    import torchaudio
    from transformers import BertTokenizer, BertModel
    HAS_BERT_VITS2 = True
except ImportError:
    HAS_BERT_VITS2 = False

# Speech recognition: try hybrid → vosk → whisper
_SPEECH_BACKEND = None
_SPEECH_OK = False
try:
    from _speech_recognition_hybrid import init_speech_recognition, speech_to_text
    _SPEECH_OK = True
    _SPEECH_BACKEND = "hybrid"
except ImportError:
    try:
        from _speech_recognition_vosk import init_speech_recognition, speech_to_text
        _SPEECH_OK = True
        _SPEECH_BACKEND = "vosk"
    except ImportError:
        try:
            from _speech_recognition_whisper import init_speech_recognition, speech_to_text
            _SPEECH_OK = True
            _SPEECH_BACKEND = "whisper"
        except ImportError:
            pass

HAS_SPEECH_RECOGNITION = _SPEECH_OK
SPEECH_BACKEND = _SPEECH_BACKEND

# ─── Lazy globals (created on first access) ──────────────────────────────────
_client = None
_mem_mgr = None
_perm_store = None
_balance_cache = {"value": "N/A", "ts": 0.0}
search_cache = {}  # Simple dict cache for web search results

_sensitive_keys = {"api_key", "memory_api_key", "tavily_api_key"}


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def _get_mem_mgr():
    global _mem_mgr
    if _mem_mgr is None:
        try:
            from _memory_manager import MemoryManager
            db_path = str(SCRIPT_DIR / "memory" / "orca_memory.db")
            _mem_mgr = MemoryManager(db_path)
        except ImportError:
            _mem_mgr = False
        except Exception:
            _mem_mgr = False
    return _mem_mgr if _mem_mgr is not False else None


def ensure_pkg(pkg_name: str, import_name: str = "") -> bool:
    """Ensure a Python package is installed. Returns True if available."""
    if not import_name:
        import_name = pkg_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        if AUTO_INSTALL_DEPS:
            import subprocess, sys
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                return False
        return False


def _get_perm_store():
    global _perm_store
    if _perm_store is None:
        from orca_code.permissions import PermissionStore
        _perm_store = PermissionStore()
    return _perm_store


# ─── Module-level __getattr__ for backward compat with lazy globals ──────────

def __getattr__(name: str):
    if name == "client":
        return _get_client()
    if name == "mem_mgr":
        return _get_mem_mgr()
    if name == "perm_store":
        return _get_perm_store()
    if name == "HAS_MEMORY":
        return _get_mem_mgr() is not None
    if name == "_load_txt_config":
        from orca_code.infrastructure.config_loader import _load_txt as fn
        globals()["_load_txt_config"] = fn
        return fn
    raise AttributeError(f"module 'orca_code.config' has no attribute '{name}'")


# ─── Helper functions ────────────────────────────────────────────────────────

def get_api_balance() -> str:
    now = __import__('time').time()
    if now - _balance_cache["ts"] < 60:
        return _balance_cache["value"]
    if not API_KEY or IS_LOCAL:
        return "N/A"
    try:
        if "deepseek" in BASE_URL.lower():
            import requests
            resp = requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                bal = data.get("balance_infos", [{}])[0].get("total_balance", "?")
                _balance_cache["value"] = str(bal)
                _balance_cache["ts"] = now
                return str(bal)
    except Exception:
        pass
    return "N/A"


# CLI command handlers (handle_config_cmd, handle_profile_cmd)
# have been moved to orca_code.cli.commands. Import from there directly.
