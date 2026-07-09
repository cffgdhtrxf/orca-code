"""orca_code.config — Configuration globals and lazy client initialization.

Thin compatibility layer. Pure config loading is in infrastructure/config_loader.
Expensive globals (client, mem_mgr) are created lazily on first access.

Importing this module is now fast — no OpenAI client created at import time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Console (lightweight — Rich console creation is cheap)
from rich.console import Console

# ─── Pure config loading (from config_loader) ────────────────────────────────
from orca_code.infrastructure.config_loader import (
    load_config,
)

# Terminal-aware Console: use truecolor on modern terminals, 256-color on
# legacy cmd.exe to avoid ANSI state machine corruption from 24-bit codes.
from orca_code.infrastructure.platform import TerminalInfo  # noqa: E402
console = Console(
    force_terminal=True,
    color_system=TerminalInfo.suggested_color_system(),
)

# ─── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.parent.resolve()
BASE_DIR = SCRIPT_DIR
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
# SecretStore resolves API keys via: env var > keychain > encrypted file > config
from orca_code.infrastructure.secrets import SecretStore

_secret_store = SecretStore()

API_KEY: str = _secret_store.resolve("api_key", CONFIG["api_key"])
BASE_URL: str = CONFIG["base_url"]
MODEL: str = CONFIG["model_name"]
MAX_OUTPUT_TOKENS: int = int(CONFIG["max_output_tokens"])
ENABLE_THINK_MODE: bool = str(CONFIG["enable_think_mode"]).lower() == "true"
SILENT_CMD: bool = str(CONFIG["silent_cmd"]).lower() == "true"
TAVILY_API_KEY: str = _secret_store.resolve("tavily_api_key", CONFIG["tavily_api_key"])
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
VISION_API_KEY: str = _secret_store.resolve("vision_api_key", CONFIG.get("vision_api_key", "")) or API_KEY

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

# ─── Compression config (headroom) ──────────────────────────────────────────
COMPRESS_CONFIG: dict = CONFIG.get("compress_config", {})
COMPRESS_USER_MSGS: bool = str(COMPRESS_CONFIG.get("compress_user_messages", False)).lower() == "true"
COMPRESS_SYSTEM_MSGS: bool = str(COMPRESS_CONFIG.get("compress_system_messages", True)).lower() == "true"
COMPRESS_PROTECT_RECENT: int = int(COMPRESS_CONFIG.get("protect_recent", 4))
COMPRESS_TARGET_RATIO: float | None = COMPRESS_CONFIG.get("target_ratio", None)
COMPRESS_MODEL: str | None = COMPRESS_CONFIG.get("compress_model", None)

# Terminal width — queried dynamically so it stays correct after resize.
# 80-column fallback when the OS can't report terminal size.
_TERM_WIDTH_FALLBACK: int = 80

try:
    _TERM_WIDTH_INIT = os.get_terminal_size().columns
except Exception:
    _TERM_WIDTH_INIT = _TERM_WIDTH_FALLBACK

# Static snapshot kept for backward compat (used only at startup by show_welcome).
TERM_WIDTH: int = _TERM_WIDTH_INIT


def get_term_width() -> int:
    """Query terminal width dynamically. Safe to call at any time.

    Unlike the static TERM_WIDTH constant (captured at import time), this
    re-queries the OS on every call, so it stays correct after terminal resize.
    """
    try:
        return os.get_terminal_size().columns
    except Exception:
        return _TERM_WIDTH_FALLBACK

# ─── Plaintext API key warning (non-blocking) ──────────────────────────────
# Orca Code 的设计哲学是开箱即用：直接修改 config.json、填入密钥即可运行。
# 虽然推荐使用环境变量 / 系统密钥链，但明文密钥不会阻止启动。
# 参见 AGENTS.md 中的 "开箱即用" 原则。
from orca_code.infrastructure.secrets import warn_plaintext_keys

_key_warnings = warn_plaintext_keys(CONFIG)
for _w in _key_warnings:
    console.print(f"[yellow]{_w}[/yellow]")

# Permission
from orca_code.permissions import PermissionMode

PERMISSION_MODE = PermissionMode("yolo")
PERMISSION_RULES: dict[str, str] = CONFIG.get("permission_rules", {})

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
    from transformers import BertModel, BertTokenizer
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
# search_cache, _balance_cache, ensure_pkg, get_api_balance → infrastructure/helpers
from orca_code.infrastructure.helpers import (  # noqa: E402, F401
    ensure_pkg,
    get_api_balance,
    search_cache,
)

_sensitive_keys = {"api_key", "memory_api_key", "tavily_api_key"}


def _get_client():
    global _client
    if _client is None:
        if not API_KEY:
            console.print("[yellow][WARN] No API key configured. Set api_key in config.json or set ORCA_API_KEY env var.[/yellow]")
            return None
        import httpx as _httpx
        from openai import OpenAI
        # ── P2-56: Proxy support ─────────────────────────────────────────
        _proxy = CONFIG.get("proxy") or CONFIG.get("http_proxy") or ""
        _http_client = None
        if _proxy:
            _http_client = _httpx.Client(proxy=_proxy)
        try:
            _client = OpenAI(api_key=API_KEY, base_url=BASE_URL, http_client=_http_client)
        except Exception as e:
            console.print(f"[bold red]错误: 无法初始化 API 客户端 — {e}[/bold red]")
            raise RuntimeError(
                f"API 客户端初始化失败。请检查 config.json 中的 base_url "
                f"({BASE_URL}) 和 api_key 是否正确。错误: {e}"
            ) from e
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


# ensure_pkg is imported from orca_code.infrastructure.helpers

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


# get_api_balance is imported from orca_code.infrastructure.helpers


# CLI command handlers (handle_config_cmd, handle_profile_cmd)
# have been moved to orca_code.cli.commands. Import from there directly.
