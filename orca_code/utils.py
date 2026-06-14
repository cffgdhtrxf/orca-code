"""orca_code.utils — Encoding, paths, tokens, cleanup."""

import json
import re
import shutil
from pathlib import Path

from orca_code.config import IS_DEEPSEEK, SCRIPT_DIR, TEMP_DIR, WORKING_DIR


def _detect_encoding(path: str) -> str:
    p = Path(path)
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        from charset_normalizer import from_bytes
        result = from_bytes(raw).best()
        if result:
            return str(result.encoding)
    except ImportError:
        pass
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"
def resolve_tool_path(path_str: str, force_temp: bool = False) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    # Path with directory prefix → output/ base (strip user's dir, just use filename)
    # Bare filename → temp/ if scratch-like, else output/
    if force_temp:
        return SCRIPT_DIR / "temp" / p.name
    if str(p.parent) != '.':
        return SCRIPT_DIR / "output" / p.name
    is_temp = any(kw in p.stem.lower() for kw in ['temp', 'test', 'tmp', '_scratch'])
    if is_temp:
        return SCRIPT_DIR / "temp" / p.name
    return SCRIPT_DIR / "output" / p.name
_FORBIDDEN_DIRS = {"system32", "etc", ".ssh", "Windows", "AppData\\Roaming\\Microsoft"}
_FORBIDDEN_NAMES = {"config.json", "config.local.json", "requirements.txt",
                    "start.bat", "start_local.bat", "start.sh"}
_FORBIDDEN_SUFFIXES = set()
_FORBIDDEN_DIRS_INTERNAL = set()
def _validate_write_path(path: str) -> tuple:
    p = resolve_tool_path(path).resolve()
    try:
        p.relative_to(SCRIPT_DIR.resolve())
    except ValueError:
        return p, f"错误: 禁止写入沙箱外路径 - {path}"
    if any(part.lower() in _FORBIDDEN_DIRS for part in p.parts):
        return p, f"错误: 禁止写入敏感目录 - {path}"
    # Block writing to config files and source code
    if p.name.lower() in _FORBIDDEN_NAMES:
        return p, f"错误: 禁止修改项目配置文件 - {p.name}"
    if p.suffix.lower() in _FORBIDDEN_SUFFIXES:
        return p, f"错误: 禁止修改源代码文件 - {p.name}"
    if any(d.lower() in _FORBIDDEN_DIRS_INTERNAL for d in p.parts):
        return p, f"错误: 禁止写入受保护目录 - {path}"
    return p, None
def _estimate_tokens(text: str) -> int:
    """Count tokens. DeepSeek models use official tokenizer; others use heuristic."""
    if not text:
        return 0
    if IS_DEEPSEEK:
        try:
            from _token_counter import count
            return count(text)
        except ImportError:
            pass  # fall through to heuristic
    # Heuristic: Chinese ~1.5 chars/token, English ~4 chars/token
    cn = len(re.findall(r"[一-鿿]", text))
    other = len(text) - cn
    return max(1, int(cn / 1.5 + other / 4))
def cleanup_temp_files(generated_files: set = None) -> str:
    removed = 0
    if generated_files:
        temp_keywords = ['temp', 'test', 'tmp', 'script', 'generate']
        for f_path in list(generated_files):
            p = Path(f_path)
            if p.exists() and str(p.resolve()).startswith(str(SCRIPT_DIR.resolve())):
                if p.suffix == '.py' and any(kw in p.stem.lower() for kw in temp_keywords):
                    try:
                        p.unlink()
                        removed += 1
                    except Exception:
                        pass
    for pat in ("temp_*.py", "test_*.py", "tmp_*"):
        for f in Path(WORKING_DIR).glob(pat):
            if f.is_file():
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
    if TEMP_DIR.is_dir():
        for f in TEMP_DIR.iterdir():
            try:
                if f.is_file():
                    f.unlink()
                    removed += 1
                elif f.is_dir():
                    shutil.rmtree(f)
                    removed += 1
            except Exception:
                pass
    return f"已清理 {removed} 个临时文件" if removed else ""
def fix_truncated_json(json_str: str):
    json_str = json_str.strip()
    if not json_str:
        return '{}', True
    try:
        json.loads(json_str)
        return json_str, False
    except json.JSONDecodeError:
        pass
    fixed = json_str
    for suffix in ('"', '"]', '"}', '"}]', '"}}', '"]}', '"]}]', '"}]}}'):
        try:
            json.loads(fixed + suffix)
            return fixed + suffix, True
        except json.JSONDecodeError:
            continue
    stack = []
    in_string = False
    escape_next = False
    for ch in fixed:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{' or ch == ']' and stack and stack[-1] == '[':
            stack.pop()
    if in_string:
        fixed += '"'
    while stack:
        opener = stack.pop()
        fixed += '}' if opener == '{' else ']'
    try:
        json.loads(fixed)
        return fixed, True
    except json.JSONDecodeError:
        return json_str, False
def _strip_html(text):
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return re.sub(r'[ \t]{2,}', ' ', text).strip()
def _sanitize_for_save(obj):
    if isinstance(obj, dict):
        return {
            k: ("sk-***" if (k == "api_key" and isinstance(v, str) and v.startswith("sk-"))
                else _sanitize_for_save(v))
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [_sanitize_for_save(v) for v in obj]
    return obj
def _sanitize_surrogates(text: str, replacement: str = "\ufffd") -> str:
    """Replace lone surrogate characters that can't be encoded to UTF-8.

    Surrogates (U+D800-U+DFFF) are invalid in UTF-8 and cause
    "'utf-8' codec can't encode character" errors when writing to stdout.
    """
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _sanitize_ansi(text: str) -> str:
    """[Fix 4] Remove or escape ANSI escape sequences from text."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
