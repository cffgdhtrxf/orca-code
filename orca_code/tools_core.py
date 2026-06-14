
import getpass
import glob as glob_mod
import logging
import os
import platform
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from orca_code.config import CMD_TIMEOUT, CONFIG_JSON, PERMISSION_MODE, SILENT_CMD, WORKING_DIR
from orca_code.security import check_command_safety, check_mode_command
from orca_code.utils import _detect_encoding, _validate_write_path

"""orca_code.tools_core — Core tools: execute, read, write, list, search."""


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
        disk = psutil.disk_usage(str(WORKING_DIR))
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
def execute_command(command: str, working_dir: str = None, use_session: bool = False) -> str:
    """Execute a shell command.

    Args:
        command: The command to execute.
        working_dir: Working directory for this command.
        use_session: If True, run in a persistent shell session that keeps
                     env vars, cwd, and aliases across calls (P2-40).
    """
    # Layer 0 safety net (always-on, even in YOLO)
    is_yolo = PERMISSION_MODE.value == "yolo"
    safe, reason = check_command_safety(command, yolo=is_yolo)
    if not safe:
        return f"SECURITY BLOCK: {reason}"

    # Layer 0.5 mode-based command check (read-only/auto restrictions)
    safe, reason = check_mode_command(command, PERMISSION_MODE)
    if not safe:
        return f"SECURITY BLOCK: {reason}"

    # ── P2-40: Persistent shell session ──────────────────────────────────
    if use_session:
        try:
            from orca_code.shell_session import get_shell_session
            shell = get_shell_session()
            return shell.run(command, timeout=CMD_TIMEOUT, cwd=working_dir)
        except Exception:
            pass  # Fall through to normal execution
    # All Windows cmd built-ins are allowed; wrap with cmd /c
    _CMD_BUILTINS = {"type", "dir", "echo", "ver", "date", "time", "cd", "cls",
                     "copy", "start", "del", "move", "ren", "mkdir", "rmdir", "set"}
    _PS_COMMANDS = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}

    # Detect PowerShell syntax — shlex.split doesn't understand pipes, variables,
    # or cmdlet patterns. Pass as a single command string to powershell -Command.
    _PS_SYNTAX = any(
        kw in command for kw in ('|', '$_', '$env:', 'Get-', 'Set-', 'New-',
        'Remove-', 'Invoke-', 'Write-', 'Out-', 'Export-', 'Import-',
        'ConvertTo-', 'Start-Process', 'Stop-Process', 'Test-', 'Where-',
        'ForEach-Object', 'Select-Object', 'Sort-Object', 'Group-Object',
        '% {', '? {', '-Command ', '-ExecutionPolicy')
    )
    _is_ps = False
    if _PS_SYNTAX and sys.platform == 'win32':
        _is_ps = True
        base_cmd = 'powershell'
        cmd_list = ['powershell', '-Command', command]
    else:
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

    _use_cmd_wrapper = False
    _is_gui_launch = False
    if _is_ps:
        _is_gui_launch = True  # don't hide window for interactive PS
    elif sys.platform == "win32" and base_cmd in _CMD_BUILTINS:
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
        # Auto-trigger LSP diagnostics
        try:
            from orca_code.lsp import auto_diagnose
            auto_diagnose(str(p))
        except ImportError:
            pass
        return f"已写入 {path} ({len(content)} 字符)"
    except Exception as e:
        logging.error(f"write_file error: {e}")
        return f"错误: {e}"

def edit_file(path: str, old_string: str, new_string: str, hashline: str | None = None) -> str:
    """精确字符串替换。old_string必须在文件中唯一出现。

    支持 hashline 锚定（P1-10）：提供 "L3:hash" → 验证对应行的内容哈希，
    如果文件已更改则拒绝修改（stale anchor detection）。"""
    p = Path(path)
    if not p.exists():
        return f"错误: 文件不存在 - {path}"
    if p.stat().st_size > 5 * 1024 * 1024:
        return "错误: 文件过大(>5MB)"
    if not old_string:
        return "错误: old_string不能为空"
    try:
        enc = _detect_encoding(path)
        original = p.read_text(encoding=enc, errors="replace")
    except Exception as e:
        return f"错误: 读取文件失败 - {e}"

    # ── P1-10: Hashline validation ────────────────────────────────────────
    if hashline:
        lines = original.split("\n")
        for entry in hashline.split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                # Format: "L<num>:<hash>" — e.g. "L42:a1b2c3"
                if ":" not in entry:
                    continue
                prefix, expected_hash = entry.split(":", 1)
                line_num = int(prefix.lstrip("L")) - 1  # 1-based → 0-based
                if 0 <= line_num < len(lines):
                    actual_hash = _hash_line(lines[line_num])
                    if actual_hash[:6] != expected_hash[:6]:
                        return (f"错误: hashline 锚定失败 — 第{line_num + 1}行内容已更改。"
                                f" 期望 {expected_hash[:6]}，实际 {actual_hash[:6]}。"
                                f" 文件可能已被修改，请重新读取后重试。")
            except (ValueError, IndexError):
                pass  # invalid hashline entry, skip

    count = original.count(old_string)
    if count == 0:
        return f"错误: 未找到匹配的文本。old_string在文件中不存在。\n文件前200字符: {original[:200]}"
    if count > 1:
        # Find all occurrences and show context
        lines = []
        idx = 0
        for i in range(min(count, 5)):
            pos = original.find(old_string, idx)
            line_num = original[:pos].count('\n') + 1
            lines.append(f"  第{line_num}行 (位置{pos})")
            idx = pos + len(old_string)
        if count > 5:
            lines.append(f"  ... 还有 {count - 5} 处")
        return (f"错误: old_string出现了{count}次，不够唯一。请包含更多上下文使匹配唯一。\n"
                f"出现位置:\n" + "\n".join(lines))

    new_content = original.replace(old_string, new_string, 1)

    # Validate: for Python files, verify AST
    if p.suffix == '.py':
        import ast as _ast
        try:
            _ast.parse(new_content)
        except SyntaxError as e:
            return f"错误: 修改后代码有语法错误 — {e}\n修改未保存，请修正后重试。"

    # Atomic write
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(p)
    try:
        from orca_code.lsp import auto_diagnose
        auto_diagnose(str(p))
    except ImportError:
        pass
    return f"已编辑 {path}: 1处替换 ({len(old_string)}→{len(new_string)}字符)"


def _hash_line(line: str) -> str:
    """Compute a short content hash for a single line (FNV-1a based)."""
    h = 0x811c9dc5
    for ch in line:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"

def apply_diff(path: str, diff_text: str) -> str:
    """应用unified diff到文件。支持标准diff格式（git diff / diff -u输出）。
    每个hunk独立应用，失败时回退整个文件。"""
    p = Path(path)
    if not p.exists():
        return f"错误: 文件不存在 - {path}"

    # Try orca_native first
    try:
        from orca_native import apply_diff as _native_apply
        return _native_apply(str(p), diff_text)
    except ImportError:
        pass

    # Pure Python fallback
    try:
        enc = _detect_encoding(path)
        original = p.read_text(encoding=enc, errors="replace")
    except Exception as e:
        return f"错误: 读取文件失败 - {e}"

    orig_lines = original.splitlines(keepends=True)
    result_lines = []
    orig_idx = 0
    hunk_re = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@?(.*)$")
    hunks, current = [], None

    for line in diff_text.splitlines():
        m = hunk_re.match(line)
        if m:
            if current:
                hunks.append(current)
            current = {"old_start": int(m.group(1)),
                       "lines": []}
        elif current:
            if line.startswith('+') and not line.startswith('+++'):
                current["lines"].append(('+', line[1:] + '\n'))
            elif line.startswith('-') and not line.startswith('---'):
                current["lines"].append(('-', line[1:] + '\n'))
            elif line.startswith(' '):
                current["lines"].append((' ', line[1:] + '\n'))
            elif line == '':
                current["lines"].append((' ', '\n'))
    if current:
        hunks.append(current)

    if not hunks:
        return "错误: diff中未找到有效的hunk（需要@@ -x,y +a,b @@格式）"

    for hunk in hunks:
        hunk_start = max(0, hunk["old_start"] - 1)
        while orig_idx < hunk_start and orig_idx < len(orig_lines):
            result_lines.append(orig_lines[orig_idx])
            orig_idx += 1
        for tag, text in hunk["lines"]:
            if tag == ' ':
                if orig_idx < len(orig_lines):
                    result_lines.append(orig_lines[orig_idx])
                    orig_idx += 1
                else:
                    result_lines.append(text)
            elif tag == '+':
                result_lines.append(text)
            elif tag == '-':
                if orig_idx < len(orig_lines):
                    orig_idx += 1

    while orig_idx < len(orig_lines):
        result_lines.append(orig_lines[orig_idx])
        orig_idx += 1

    new_content = ''.join(result_lines)

    # Validate Python syntax
    if p.suffix == '.py':
        import ast as _ast
        try:
            _ast.parse(new_content)
        except SyntaxError as e:
            return f"错误: diff应用后代码有语法错误 — {e}\n未保存。"

    # Atomic write
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(p)
    try:
        from orca_code.lsp import auto_diagnose
        auto_diagnose(str(p))
    except ImportError:
        pass

    return f"Diff已应用: {len(hunks)}个hunk | 文件大小: {len(new_content)}字符"

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

    # Try orca_native Rust engine first (.gitignore-aware, parallel)
    try:
        from orca_native import walk_files as _native_walk
        result = _native_walk(str(base), pattern, 200)
        if result and not result.startswith("Error"):
            return "\n".join(f"  {r}" for r in result.split("\n")[:200])
    except ImportError:
        pass

    try:
        results = sorted(glob_mod.glob(pattern, root_dir=str(base), recursive=True))
        if not results:
            return f"未找到匹配 '{pattern}' 的文件"
        return "\n".join(f"  {r}" for r in results[:200])
    except Exception as e:
        return f"错误: {e}"
def search_content(pattern: str, directory: str = None, file_filter: str = None) -> str:
    base = Path(directory) if directory else Path(WORKING_DIR)

    # Try orca_native Rust engine first (10-100x faster on large projects)
    try:
        from orca_native import search_content as _native_search
        result = _native_search(pattern, str(base), file_filter, 100, 0)
        if result and not result.startswith("Error"):
            return result
    except ImportError:
        pass

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
