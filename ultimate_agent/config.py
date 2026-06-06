"""ultimate_agent.config — Configuration, globals, cache, client.

Orca Code — 桌面 AI 助手
"""
# ============================================================
# 1. 导入 & 平台初始化
# ============================================================
import os, sys, json, subprocess, glob as glob_mod, time, re, platform, getpass, asyncio, unicodedata
import tempfile, shutil, inspect, threading, logging, shlex, ipaddress, ast as _ast
import urllib.request, urllib.error, urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleOutputCP(65001)
    kernel32.SetConsoleCP(65001)
    try:
        STDOUT = -11
        ENABLE_VT = 0x0004
        handle = kernel32.GetStdHandle(STDOUT)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | ENABLE_VT)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import tenacity
import requests
import openai
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table

console = Console()

# ---- C版: 语音识别导入 (三级降级) ----
try:
    from _speech_recognition_hybrid import init_speech_recognition, speech_to_text
    HAS_SPEECH_RECOGNITION = True
    SPEECH_BACKEND = "hybrid"
except ImportError:
    try:
        from _speech_recognition_vosk import init_speech_recognition, speech_to_text
        HAS_SPEECH_RECOGNITION = True
        SPEECH_BACKEND = "vosk"
    except ImportError:
        try:
            from _speech_recognition_whisper import init_speech_recognition, speech_to_text
            HAS_SPEECH_RECOGNITION = True
            SPEECH_BACKEND = "whisper"
        except ImportError:
            HAS_SPEECH_RECOGNITION = False
            SPEECH_BACKEND = None

# ---- C版: 可选依赖检测 ----
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

# ============================================================
# 2. 配置系统 (JSON主 + TXT兼容回退)
# ============================================================
SCRIPT_DIR = Path(__file__).parent.parent.resolve() if "__file__" in dir() else Path.cwd()  # parent.parent: project root from ultimate_agent/ package
CONFIG_JSON = SCRIPT_DIR / "config.json"
CONFIG_TXT = SCRIPT_DIR / "配置文件.txt"

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
}

# TXT key name mapping for B版 compatibility
_TXT_KEY_MAP = {
    "API_KEY": "api_key", "BASE_URL": "base_url", "MODEL": "model_name",
    "TAVILY_API_KEY": "tavily_api_key", "THINKING_ENABLED": "enable_think_mode",
    "REASONING_EFFORT": "reasoning_effort", "MAX_OUTPUT_TOKENS": "max_output_tokens",
    "KEEP_BLOCKS": "keep_blocks", "MAX_WORKERS": "max_workers",
    "PERSONA": "persona", "CMD_TIMEOUT": "cmd_timeout",
}

def _load_json_config() -> dict:
    if not CONFIG_JSON.exists():
        return {}
    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_txt_config() -> dict:
    if not CONFIG_TXT.exists():
        return {}
    cfg = {}
    for line in CONFIG_TXT.read_text(encoding="utf-8").splitlines():
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
    # [FIX] Type coercion: TXT config values are always strings, coerce to expected types
    _INT_KEYS = ("max_output_tokens", "context_max_tokens", "max_workers",
                 "keep_last_rounds", "keep_blocks", "cmd_timeout")
    _BOOL_KEYS = ("enable_think_mode", "silent_cmd", "auto_install_deps",
                  "enable_gui_auto", "enable_browser_auto", "enable_tts",
                  "enable_voice", "local_model")
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

def mask_key(key: str) -> str:
    if not key or len(key) < 10:
        return "***"
    return key[:5] + "***" + key[-3:]

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_JSON.exists():
        user = _load_json_config()
        cfg.update(user)
        return cfg
    if CONFIG_TXT.exists():
        user = _load_txt_config()
        cfg.update(user)
        console.print("[yellow]使用 TXT 配置文件 (配置文件.txt)，建议迁移到 config.json[/yellow]")
        return cfg
    # Neither exists: create JSON with defaults, continue (interactive setup handles API key)
    CONFIG_JSON.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[bold yellow]已创建默认配置文件 '{CONFIG_JSON}'，请填写 api_key 后重启！[/bold yellow]")
    return cfg  # [FIX] return defaults instead of sys.exit() — allows embedded/library use

CONFIG = load_config()
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
IS_DEEPSEEK: bool = "deepseek" in MODEL.lower() or "deepseek" in BASE_URL.lower()
IS_LOCAL: bool = str(CONFIG.get("local_model", False)).lower() == "true" or any(
    host in BASE_URL.lower() for host in ("localhost", "127.0.0.1", "192.168", "10.", "172.16", "0.0.0.0")
)
# Model family detection — drives tokenizer / prompt / param strategy
IS_GEMMA: bool = "gemma" in MODEL.lower()
IS_QWEN: bool = "qwen" in MODEL.lower()
IS_MINISTRAL: bool = any(kw in MODEL.lower() for kw in ("mistral", "ministral"))
# "Simple mode" for models that perform better with concise prompts & fewer constraints
USE_SIMPLE_PROMPT: bool = IS_GEMMA or IS_QWEN or IS_MINISTRAL
VISION_MODEL: str = CONFIG.get("vision_model", "")
VISION_BASE_URL: str = CONFIG.get("vision_base_url", "") or BASE_URL
VISION_API_KEY: str = CONFIG.get("vision_api_key", "") or API_KEY
# Auto-detect multimodal: explicit config overrides, otherwise detect from model name
_MULTIMODAL_PATTERNS = ['vl', 'vision', 'gpt-4o', 'gpt-4-turbo', 'gemini',
                        'claude', 'gemma', 'llava', 'minicpm', 'internvl',
                        'qwen2.5-vl', 'qwen-vl', 'pixtral', 'phi-3-vision']
if "multimodal" in CONFIG:
    IS_MULTIMODAL: bool = str(CONFIG.get("multimodal", False)).lower() == "true"
else:
    # Only check the MAIN model — vision model capability doesn't count
    IS_MULTIMODAL: bool = any(p in MODEL.lower() for p in _MULTIMODAL_PATTERNS)

_SENSITIVE_KEYS = {"api_key", "memory_api_key", "tavily_api_key"}

def handle_profile_cmd(user_input: str):
    """Handle /profile command: view or edit user profile."""
    parts = user_input.strip().split(maxsplit=1)
    if not HAS_MEMORY or not mem_mgr:
        console.print("[yellow]记忆系统未启用[/yellow]")
        return
    current = mem_mgr.get_meta("user_profile") or ""
    if len(parts) == 1:
        console.print()
        console.print("[bold]用户画像 (User Profile)[/bold]")
        if current:
            console.print(f"  {current}")
        else:
            console.print("  [dim](空)[/dim]")
        console.print()
        console.print("[dim]/profile add <内容>  追加[/dim]")
        console.print("[dim]/profile set <内容>  覆盖[/dim]")
        console.print("[dim]/profile clear      清空[/dim]")
        return
    action = parts[1].strip()
    if action == "clear":
        mem_mgr.set_meta("user_profile", "")
        console.print("[green]画像已清空[/green]")
    elif action.startswith("set "):
        text = action[4:].strip()
        mem_mgr.set_meta("user_profile", text[:500])
        console.print(f"[green]画像已更新: {text[:100]}[/green]")
    elif action.startswith("add "):
        text = action[4:].strip()
        new_profile = f"{current} {text}".strip()[:500]
        mem_mgr.set_meta("user_profile", new_profile)
        console.print(f"[green]已追加: {text[:100]}[/green]")
    else:
        # Treat as direct profile text (convenience)
        mem_mgr.set_meta("user_profile", action[:500])
        console.print(f"[green]画像已更新: {action[:100]}[/green]")

def handle_config_cmd(user_input: str):
    """Handle /config command: show all config, or set a key."""
    parts = user_input.strip().split(maxsplit=1)
    if len(parts) == 1 or "=" not in parts[1]:
        # Show config
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="dim"); t.add_column()
        for k, v in sorted(CONFIG.items()):
            if k.startswith("//"):
                continue
            if k in _SENSITIVE_KEYS:
                v = mask_key(str(v))
            t.add_row(k, str(v)[:60])
        console.print(); console.print("[bold]当前配置[/bold]")
        console.print(t)
        return

    # Set config
    kv = parts[1]
    if "=" not in kv:
        console.print(f"[yellow]用法: /config key=value[/yellow]")
        return
    key, value = kv.split("=", 1)
    key = key.strip()
    value = value.strip()

    # Strip quotes if present
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]

    if key not in CONFIG:
        console.print(f"[yellow]未知配置项: {key}[/yellow]")
        return

    # Type conversion
    old = CONFIG[key]
    if isinstance(old, bool):
        value = value.lower() in ("true", "1", "yes")
    elif isinstance(old, int):
        try:
            value = int(value)
        except ValueError:
            console.print(f"[yellow]'{key}' 需要整数[/yellow]")
            return

    CONFIG[key] = value
    try:
        CONFIG_JSON.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        if key in _SENSITIVE_KEYS:
            console.print(f"[green]{key} = {mask_key(str(value))} (已保存，需重启生效)[/green]")
        else:
            console.print(f"[green]{key} = {value} (已保存，需重启生效)[/green]")
    except Exception as e:
        console.print(f"[red]保存失败: {e}[/red]")

if not API_KEY and not IS_LOCAL:
    # [FIX] Only prompt interactively if stdin is a terminal; skip during imports
    if sys.stdin.isatty():
        console.print("[bold yellow]未配置 API Key[/bold yellow]")
        console.print()
        console.print("  1. 云端模式: 输入 DeepSeek 或其他 API Key")
        console.print("  2. 本地模式: 使用 LM Studio / Ollama 等本地模型")
        console.print("  3. 退出")
        console.print()
        try:
            choice = input("请选择 (1/2/3): ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "3"
        if choice == "1":
            try:
                key = input("API Key: ").strip()
            except (EOFError, KeyboardInterrupt):
                key = ""
            if key:
                CONFIG["api_key"] = key
                CONFIG_JSON.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
                console.print(f"[green]已保存: {mask_key(key)}[/green]")
                API_KEY = key
            else:
                console.print("[red]未输入 Key，退出[/red]")
                sys.exit(1)
        elif choice == "2":
            CONFIG["local_model"] = True
            CONFIG["base_url"] = "http://localhost:1234/v1"
            CONFIG_JSON.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
            console.print("[green]已切换为本地模型模式[/green]")
            IS_LOCAL = True
            API_KEY = "lm-studio"
            BASE_URL = CONFIG["base_url"]
            MODEL = CONFIG["model_name"]
        else:
            console.print("[dim]退出。请编辑 config.json 后重试[/dim]")
            sys.exit(1)
    else:
        # Non-interactive: auto-create default config and continue
        if not CONFIG_JSON.exists():
            CONFIG_JSON.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print("[dim]非交互模式：使用默认配置（如需API Key请编辑 config.json）[/dim]")
if IS_LOCAL and (not API_KEY or API_KEY == "sk-your-api-key-here"):
    API_KEY = "lm-studio"  # LM Studio/Ollama accept any value
    console.print("[dim]本地模型模式: API Key 自动设置为占位值[/dim]")

# ============================================================
# 3. 目录设置 & 客户端初始化
# ============================================================
WORKING_DIR = os.getcwd()
SAVE_DIR = SCRIPT_DIR / "save"
TEMP_DIR = SCRIPT_DIR / "temp"
LOGS_DIR = SCRIPT_DIR / "logs"
SKILLS_DIR = SCRIPT_DIR / "skills"
OUTPUT_DIR = SCRIPT_DIR / "output"
CACHE_DIR = SCRIPT_DIR / ".cache"
MEMORY_DIR = SCRIPT_DIR / "memory"

for d in (SAVE_DIR, TEMP_DIR, LOGS_DIR, SKILLS_DIR, OUTPUT_DIR, CACHE_DIR, MEMORY_DIR):
    d.mkdir(parents=True, exist_ok=True)

try:
    logging.basicConfig(
        filename=str(SAVE_DIR / "error.log"), level=logging.ERROR,
        format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8'
    )
except Exception:
    pass

try:
    TERM_WIDTH = os.get_terminal_size().columns
except Exception:
    TERM_WIDTH = 80
if TERM_WIDTH < 40:
    TERM_WIDTH = 80

client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=openai.Timeout(300.0, connect=10.0))
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# ---- Memory System ----
try:
    from _memory_manager import MemoryManager
    mem_mgr = MemoryManager(MEMORY_DIR / "memories.db")
    HAS_MEMORY = True
except ImportError:
    HAS_MEMORY = False
    mem_mgr = None

# ---- Python REPL ----
try:
    from _python_repl import execute_python
    HAS_PYTHON_REPL = True
except ImportError:
    HAS_PYTHON_REPL = False
    def execute_python(code: str, timeout: int = 30) -> str:
        return "Error: _python_repl module not available"

# ============================================================
# 4. 依赖管理 (B版 ensure_pkg 风格)
# ============================================================
def ensure_pkg(pkg: str, imp: str = None) -> bool:
    try:
        __import__(imp or pkg)
        return True
    except ImportError:
        if not AUTO_INSTALL_DEPS:
            return False
        console.print(f"[dim]  => 自动安装: {pkg}[/dim]")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
            )
            return True
        except Exception:
            return False

console = Console()
_TXT_KEY_MAP = {
    "API_KEY": "api_key", "BASE_URL": "base_url", "MODEL": "model_name",
    "TAVILY_API_KEY": "tavily_api_key", "THINKING_ENABLED": "enable_think_mode",
    "REASONING_EFFORT": "reasoning_effort", "MAX_OUTPUT_TOKENS": "max_output_tokens",
    "KEEP_BLOCKS": "keep_blocks", "MAX_WORKERS": "max_workers",
    "PERSONA": "persona", "CMD_TIMEOUT": "cmd_timeout",
}
def _load_json_config() -> dict:
    if not CONFIG_JSON.exists():
        return {}
    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
        return json.load(f)
def _load_txt_config() -> dict:
    if not CONFIG_TXT.exists():
        return {}
    cfg = {}
    for line in CONFIG_TXT.read_text(encoding="utf-8").splitlines():
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
    # [FIX] Type coercion: TXT config values are always strings, coerce to expected types
    _INT_KEYS = ("max_output_tokens", "context_max_tokens", "max_workers",
                 "keep_last_rounds", "keep_blocks", "cmd_timeout")
    _BOOL_KEYS = ("enable_think_mode", "silent_cmd", "auto_install_deps",
                  "enable_gui_auto", "enable_browser_auto", "enable_tts",
                  "enable_voice", "local_model")
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
def mask_key(key: str) -> str:
    if not key or len(key) < 10:
        return "***"
    return key[:5] + "***" + key[-3:]
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_JSON.exists():
        user = _load_json_config()
        cfg.update(user)
        return cfg
    if CONFIG_TXT.exists():
        user = _load_txt_config()
        cfg.update(user)
        console.print("[yellow]使用 TXT 配置文件 (配置文件.txt)，建议迁移到 config.json[/yellow]")
        return cfg
    # Neither exists: create JSON with defaults, continue (interactive setup handles API key)
    CONFIG_JSON.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[bold yellow]已创建默认配置文件 '{CONFIG_JSON}'，请填写 api_key 后重启！[/bold yellow]")
    return cfg  # [FIX] return defaults instead of sys.exit() — allows embedded/library use
CONFIG = load_config()
_MULTIMODAL_PATTERNS = ['vl', 'vision', 'gpt-4o', 'gpt-4-turbo', 'gemini',
                        'claude', 'gemma', 'llava', 'minicpm', 'internvl',
                        'qwen2.5-vl', 'qwen-vl', 'pixtral', 'phi-3-vision']
_SENSITIVE_KEYS = {"api_key", "memory_api_key", "tavily_api_key"}
def handle_profile_cmd(user_input: str):
    """Handle /profile command: view or edit user profile."""
    parts = user_input.strip().split(maxsplit=1)
    if not HAS_MEMORY or not mem_mgr:
        console.print("[yellow]记忆系统未启用[/yellow]")
        return
    current = mem_mgr.get_meta("user_profile") or ""
    if len(parts) == 1:
        console.print()
        console.print("[bold]用户画像 (User Profile)[/bold]")
        if current:
            console.print(f"  {current}")
        else:
            console.print("  [dim](空)[/dim]")
        console.print()
        console.print("[dim]/profile add <内容>  追加[/dim]")
        console.print("[dim]/profile set <内容>  覆盖[/dim]")
        console.print("[dim]/profile clear      清空[/dim]")
        return
    action = parts[1].strip()
    if action == "clear":
        mem_mgr.set_meta("user_profile", "")
        console.print("[green]画像已清空[/green]")
    elif action.startswith("set "):
        text = action[4:].strip()
        mem_mgr.set_meta("user_profile", text[:500])
        console.print(f"[green]画像已更新: {text[:100]}[/green]")
    elif action.startswith("add "):
        text = action[4:].strip()
        new_profile = f"{current} {text}".strip()[:500]
        mem_mgr.set_meta("user_profile", new_profile)
        console.print(f"[green]已追加: {text[:100]}[/green]")
    else:
        # Treat as direct profile text (convenience)
        mem_mgr.set_meta("user_profile", action[:500])
        console.print(f"[green]画像已更新: {action[:100]}[/green]")
def handle_config_cmd(user_input: str):
    """Handle /config command: show all config, or set a key."""
    parts = user_input.strip().split(maxsplit=1)
    if len(parts) == 1 or "=" not in parts[1]:
        # Show config
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="dim"); t.add_column()
        for k, v in sorted(CONFIG.items()):
            if k.startswith("//"):
                continue
            if k in _SENSITIVE_KEYS:
                v = mask_key(str(v))
            t.add_row(k, str(v)[:60])
        console.print(); console.print("[bold]当前配置[/bold]")
        console.print(t)
        return

    # Set config
    kv = parts[1]
    if "=" not in kv:
        console.print(f"[yellow]用法: /config key=value[/yellow]")
        return
    key, value = kv.split("=", 1)
    key = key.strip()
    value = value.strip()

    # Strip quotes if present
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]

    if key not in CONFIG:
        console.print(f"[yellow]未知配置项: {key}[/yellow]")
        return

    # Type conversion
    old = CONFIG[key]
    if isinstance(old, bool):
        value = value.lower() in ("true", "1", "yes")
    elif isinstance(old, int):
        try:
            value = int(value)
        except ValueError:
            console.print(f"[yellow]'{key}' 需要整数[/yellow]")
            return

    CONFIG[key] = value
    try:
        CONFIG_JSON.write_text(json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        if key in _SENSITIVE_KEYS:
            console.print(f"[green]{key} = {mask_key(str(value))} (已保存，需重启生效)[/green]")
        else:
            console.print(f"[green]{key} = {value} (已保存，需重启生效)[/green]")
    except Exception as e:
        console.print(f"[red]保存失败: {e}[/red]")
WORKING_DIR = os.getcwd()
SAVE_DIR = SCRIPT_DIR / "save"
TEMP_DIR = SCRIPT_DIR / "temp"
LOGS_DIR = SCRIPT_DIR / "logs"
SKILLS_DIR = SCRIPT_DIR / "skills"
OUTPUT_DIR = SCRIPT_DIR / "output"
CACHE_DIR = SCRIPT_DIR / ".cache"
MEMORY_DIR = SCRIPT_DIR / "memory"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=openai.Timeout(300.0, connect=10.0))
HTTP_SESSION = requests.Session()
def ensure_pkg(pkg: str, imp: str = None) -> bool:
    try:
        __import__(imp or pkg)
        return True
    except ImportError:
        if not AUTO_INSTALL_DEPS:
            return False
        console.print(f"[dim]  => 自动安装: {pkg}[/dim]")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
            )
            return True
        except Exception:
            return False
class SimpleCache:
    def __init__(self, ttl: int = 300):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            if key in self._cache:
                ts, val = self._cache[key]
                if time.time() - ts < self._ttl:
                    return val
                del self._cache[key]
            return None

    def set(self, key: str, value: Any):
        with self._lock:
            self._cache[key] = (time.time(), value)
search_cache = SimpleCache(ttl=600)
page_cache = SimpleCache(ttl=300)
_balance_cache = {"value": "查询中...", "time": 0}
_balance_lock = threading.Lock()
def get_api_balance() -> str:
    if IS_LOCAL:
        return "本地模型"
    with _balance_lock:
        now = time.time()
        if now - _balance_cache["time"] < 30:
            return _balance_cache["value"]
    try:
        if "deepseek" in BASE_URL.lower():
            base = BASE_URL.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            url = f"{base}/user/balance"
            res = requests.get(url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                with _balance_lock:
                    if "balance_infos" in data and len(data["balance_infos"]) > 0:
                        balance = data["balance_infos"][0].get("total_balance", "未知")
                        currency = data["balance_infos"][0].get("currency", "CNY")
                        _balance_cache["value"] = f"{balance} {currency}"
                    else:
                        _balance_cache["value"] = "未知"
            else:
                with _balance_lock:
                    _balance_cache["value"] = "不支持"
        else:
            with _balance_lock:
                _balance_cache["value"] = "非DS平台"
    except Exception:
        with _balance_lock:
            _balance_cache["value"] = "查询失败"
    with _balance_lock:
        _balance_cache["time"] = now
    return _balance_cache["value"]