
import os, sys, re, subprocess, shlex, platform, getpass
import glob as glob_mod
from pathlib import Path
from datetime import datetime
import logging
from ultimate_agent.config import (CONFIG, API_KEY, BASE_URL, MODEL,
    CMD_TIMEOUT, SILENT_CMD, WORKING_DIR, SCRIPT_DIR, TERM_WIDTH, CONFIG_JSON, console)
from ultimate_agent.utils import _detect_encoding, _validate_write_path, _estimate_tokens
from ultimate_agent.security import _DANGEROUS_PATTERNS

"""ultimate_agent.tools_core — Core tools: execute, read, write, list, search."""


def get_device_type() -> str:
    system = platform.system()
    p = platform.platform().lower()
    if system in ("Windows", "Darwin"):
        return "Desktop/Laptop"
    if system == "Linux":
        if "android" in p:
            return "Phone"
        if any(platform.machine().lower().startswith(a) for a in ("armv7l", "armv6l", "aarch64", "arm64")):
            return "Mobile/Embedded"
        return "Desktop/Server"
    return "Unknown"
def get_system_info() -> str:
    now = datetime.now()
    lines = [
        f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})",
        f"用户: {getpass.getuser()}",
        f"系统: {platform.system()} ({platform.platform()})",
        f"设备: {get_device_type()}",
        f"Python: {platform.python_version()}",
        f"工作目录: {WORKING_DIR}",
    ]
    try:
        import psutil
        cpu_phys = psutil.cpu_count(logical=False) or 0
        cpu_log = psutil.cpu_count(logical=True) or 0
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(WORKING_DIR)
        lines.extend([
            f"CPU: {cpu_phys}物理核 / {cpu_log}逻辑核",
            f"内存: {round(mem.total / 1024**3, 1)}GB 总 / {round(mem.available / 1024**3, 1)}GB 可用",
            f"磁盘: {round(disk.total / 1024**3, 1)}GB 总 / {round(disk.free / 1024**3, 1)}GB 可用",
        ])
    except ImportError:
        pass
    return "\n".join(lines)
def get_env_summary() -> str:
    return f"[系统环境摘要]\n{get_system_info()}\n配置文件: {CONFIG_JSON.absolute()}"
def execute_command(command: str, working_dir: str = None) -> str:
    for pat in _DANGEROUS_PATTERNS:
        if re.search(pat, command, re.IGNORECASE):
            return f"错误: 命令包含危险模式，已拦截"
    try:
        cmd_list = shlex.split(command, posix=(sys.platform != "win32"))
    except ValueError as e:
        return f"错误: 命令解析失败 - {e}"
    if not cmd_list:
        return "错误: 空命令"
    base_cmd = Path(cmd_list[0]).name.lower()
    # Only block commands that can permanently destroy the system
    if base_cmd in {"format"}:
        return f"错误: 命令 {base_cmd} 已被禁止（会破坏文件系统）"
    # All Windows cmd built-ins are allowed; wrap with cmd /c
    _CMD_BUILTINS = {"type", "dir", "echo", "ver", "date", "time", "cd", "cls",
                     "copy", "start", "del", "move", "ren", "mkdir", "rmdir", "set"}
    _PS_COMMANDS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    _use_cmd_wrapper = False
    _is_gui_launch = False
    if sys.platform == "win32" and base_cmd in _CMD_BUILTINS:
        cmd_list = ["cmd", "/c"] + cmd_list
        _use_cmd_wrapper = True
        if base_cmd == "start":
            _is_gui_launch = True
    elif sys.platform == "win32" and base_cmd in _PS_COMMANDS:
        _is_gui_launch = True
    # Allow all shell operators — user is in control of their machine
    cwd = working_dir or WORKING_DIR
    # [FIX] Auto-redirect .exe/.bat/.cmd to start "" for reliable GUI launch
    if sys.platform == "win32" and not _use_cmd_wrapper:
        if base_cmd.endswith(('.exe', '.bat', '.cmd', '.msc', '.cpl')):
            cmd_list = ["cmd", "/c", "start", ""] + cmd_list
            _use_cmd_wrapper = True
            _is_gui_launch = True

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    creationflags = 0x08000000 if (sys.platform == "win32" and SILENT_CMD and not _is_gui_launch) else 0
    try:
        # cmd.exe outputs in system locale (GBK on Chinese Windows), not UTF-8
        _enc = None if _use_cmd_wrapper else "utf-8"
        result = subprocess.run(
            cmd_list, shell=False, cwd=cwd,
            capture_output=True, text=True, timeout=CMD_TIMEOUT,
            env=env, encoding=_enc, errors="replace",
            creationflags=creationflags,
        )
        output = (result.stdout or "").strip() or (result.stderr or "").strip()
        return output[:8000] if len(output) > 8000 else output
    except FileNotFoundError:
        return f"错误: 命令未找到 - {cmd_list[0]}"
    except subprocess.TimeoutExpired:
        return f"错误: 命令执行超时({CMD_TIMEOUT}s)"
    except Exception as e:
        return f"错误: {e}"
def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"错误: 文件不存在 - {path}"
    if p.stat().st_size > 5 * 1024 * 1024:
        return "错误: 文件过大(>5MB)"
    try:
        enc = _detect_encoding(path)
        return p.read_text(encoding=enc, errors="replace")
    except Exception as e:
        return f"错误: {e}"
def write_file(path: str, content: str) -> str:
    p, error = _validate_write_path(path)
    if error:
        return error
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # [FIX] Atomic write: write to temp file then replace — prevents corruption on crash
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(p)
        return f"已写入 {path} ({len(content)} 字符)"
    except Exception as e:
        logging.error(f"write_file error: {e}")
        return f"错误: {e}"
def list_files(path: str = None) -> str:
    p = Path(path) if path else Path(WORKING_DIR)
    if not p.is_dir():
        return f"错误: 不是目录 - {p}"
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for item in items:
            tag = "[DIR]" if item.is_dir() else "[FILE]"
            size = ""
            if item.is_file():
                try:
                    s = item.stat().st_size
                    if s < 1024:
                        size = f" ({s}B)"
                    elif s < 1024 * 1024:
                        size = f" ({s / 1024:.1f}KB)"
                    else:
                        size = f" ({s / 1024 / 1024:.1f}MB)"
                except OSError:
                    pass
            lines.append(f"  {tag} {item.name}{size}")
        return "\n".join(lines) if lines else "(空目录)"
    except Exception as e:
        return f"错误: {e}"
def search_files(pattern: str, directory: str = None) -> str:
    base = Path(directory) if directory else Path(WORKING_DIR)
    try:
        results = sorted(glob_mod.glob(pattern, root_dir=str(base), recursive=True))
        if not results:
            return f"未找到匹配 '{pattern}' 的文件"
        return "\n".join(f"  {r}" for r in results[:200])
    except Exception as e:
        return f"错误: {e}"
def search_content(pattern: str, directory: str = None, file_filter: str = None) -> str:
    base = Path(directory) if directory else Path(WORKING_DIR)
    pattern_lower = pattern.lower()
    glob_pattern = file_filter or "*"
    # Windows: try findstr first (faster)
    if sys.platform == "win32":
        try:
            cmd = ["findstr", "/S", "/I", "/N", pattern]
            if file_filter:
                cmd.append(file_filter)
            result = subprocess.run(
                cmd, cwd=str(base), capture_output=True, text=True, timeout=30,
                encoding=None, errors="replace"
            )
            output = result.stdout.strip()
            if output:
                return "\n".join(output.split("\n")[:100])
        except Exception:
            pass
    results = []
    # [FIX] Cross-platform fast path: try ripgrep if available
    rg_found = False
    if not sys.platform == "win32":
        try:
            rg_cmd = ["rg", "--no-heading", "--line-number", "--max-count=100", pattern]
            if file_filter:
                rg_cmd.extend(["--glob", file_filter])
            rg_result = subprocess.run(
                rg_cmd, cwd=str(base), capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace"
            )
            rg_output = rg_result.stdout.strip()
            if rg_output:
                return "\n".join(rg_output.split("\n")[:100])
            rg_found = True  # rg ran but found nothing
        except Exception:
            pass

    # [FIX] Add file count guard to prevent O(n) scan on huge directories
    file_count = 0
    max_files = 2000
    for f in base.rglob(glob_pattern):
        if not f.is_file() or f.stat().st_size > 1024 * 1024:
            continue
        file_count += 1
        if file_count > max_files:
            results.append(f"... (搜索超过 {max_files} 个文件，已截断；请缩小 directory 或 file_filter)")
            break
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern_lower in line.lower():
                    results.append(f"{f.relative_to(base)}:{i}: {line.strip()[:200]}")
                    if len(results) >= 100:
                        break
        except Exception:
            continue
        if len(results) >= 100:
            break
    return "\n".join(results) if results else f"未找到匹配 '{pattern}' 的内容"