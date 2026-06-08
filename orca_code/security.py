"""orca_code.security — Safety net and skill sandbox.

Layered security model:
  Layer 0 — Always-on safety net (this module):
    Commands/patterns that are ALWAYS blocked regardless of permission mode.
    Covers: disk destruction, system takeover, data exfiltration.

  Layer 1 — Permission system (permissions.py):
    Per-tool risk levels (read/write/exec) + user policy modes.
    Handles "should this tool be allowed?" based on user preferences.

  Layer 2 — Skill sandbox (this module, _scan_skill_ast / _safe_exec_skill):
    Restricts user-authored skill scripts to a safe subset of Python.
"""

import re
import ipaddress
import urllib.parse
import ast as _ast
from pathlib import Path
from typing import Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 0 — Always-On Safety Net
# These patterns are ALWAYS blocked, even in YOLO mode.
# They cover commands that can irreversibly destroy the system.
# ═══════════════════════════════════════════════════════════════════════════════

_ALWAYS_BLOCKED = [
    # Disk destruction
    (r'(?i)(?:^|\s)format\s', "Disk format command"),
    (r'(?i)\bdd\s+if=.*of=/dev', "Raw device write"),
    (r'(?i)\bmkfs\.', "Filesystem creation (mkfs)"),

    # Recursive root deletion
    (r'(?i)\brm\s+(-[a-z]*r[a-z]*|-r[a-z]*-[a-z]*)\s+/', "Recursive root delete"),
    (r'(?i)\brmdir\s+/', "Root directory removal"),

    # Remote code execution via pipe (curl/wget → shell)
    (r'(?i)\b(curl|wget)\s+.*\|\s*(ba)?sh\b', "Remote code piped to shell"),
    (r'(?i)\b(curl|wget)\s+.*\|\s*(python|perl|ruby|node)\b', "Remote code piped to interpreter"),

    # Fork bombs
    (r'(?i):\s*\(\)\s*\{.*:\|:.*\}', "Fork bomb pattern"),

    # System shutdown / restart
    (r'(?i)\b(shutdown|reboot|halt|poweroff)\b', "System shutdown command"),

    # Encoded PowerShell commands (bypass risk)
    (r'(?i)\s-EncodedCommand\s', "Encoded PowerShell command (bypass risk)"),
    (r'(?i)\s-enc\s', "Encoded PowerShell command (bypass risk)"),
    (r'(?i)\s-e\s+\S{20,}', "Encoded PowerShell command (bypass risk)"),
]

# Commands that are blocked only in read-only and auto modes (not YOLO)
_AUTO_BLOCKED = [
    # Privilege escalation
    (r'(?i)\bsudo\b', "Privilege escalation (sudo)"),
    (r'(?i)\brunas\b', "Privilege escalation (runas)"),

    # System service manipulation
    (r'(?i)\b(systemctl|service)\s+(stop|disable|mask)', "System service control"),
    (r'(?i)\bsc\s+(stop|delete|disable)', "Windows service control"),

    # Write to system paths
    (r'(?i)\b(write|cp|mv|cat|tee)\s+.*/(etc|boot|bin|lib|sys|proc|dev)/', "System path write"),
]


def check_command_safety(command: str, yolo: bool = False) -> Tuple[bool, str]:
    """Check if a shell command is safe to execute.

    Returns (is_safe: bool, reason: str).
    Always-on patterns are always checked. Auto patterns only apply in non-YOLO.
    """
    # Always-on safety net
    for pattern, reason in _ALWAYS_BLOCKED:
        if re.search(pattern, command):
            return False, f"SECURITY BLOCK: {reason}"

    # Non-YOLO additional checks
    if not yolo:
        for pattern, reason in _AUTO_BLOCKED:
            if re.search(pattern, command):
                return False, f"SECURITY BLOCK: {reason} (use YOLO mode to bypass)"

    return True, ""


def is_safe_url(url: str) -> Tuple[bool, str]:
    """Validate a URL for web_fetch/read_webpage.

    Blocks:
      - Non-HTTP protocols (file://, ftp://, etc.)
      - Private/localhost IPs (SSRF protection)
      - Invalid hostnames

    Returns (is_safe: bool, reason: str).
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    # Protocol check
    if parsed.scheme not in ("http", "https"):
        return False, f"Protocol not allowed: {parsed.scheme}"

    if not parsed.hostname:
        return False, "No hostname in URL"

    host = parsed.hostname.lower()

    # Block localhost variants
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "Localhost URLs not allowed"

    # Block link-local
    if host.startswith("169.254."):
        return False, "Link-local addresses not allowed"

    # Block private IP ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False, f"Private/internal IP not allowed: {host}"
    except ValueError:
        pass  # Not an IP — hostname resolution happens at fetch time

    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2 — Skill Sandbox
# User-authored skills run in a restricted Python environment.
# ═══════════════════════════════════════════════════════════════════════════════

# Legacy hash for location test script validation
_TEST_LOCATION_HASH = "1949a70bb82d437571480ce084c08aa1ba9799b68c6180643212afd77ad193f4"

_SKILL_BLACKLIST = [
    "os", "sys", "subprocess", "shutil", "ctypes", "urllib", "requests",
    "socket", "http", "ftplib", "telnetlib", "smtplib",
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr", "hasattr",
    "breakpoint", "__builtins__", "__builtin__",
    "Path", "pathlib",
]

_SKILL_DANGEROUS_ATTRS = {
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__builtin__", "__import__",
    "__dict__", "__code__", "__closure__", "__func__", "__self__",
    "__init__", "__new__", "__del__", "__reduce__", "__reduce_ex__",
    "__getattribute__", "__getattr__", "__setattr__",
    "system", "popen", "exec", "eval", "compile",
}

_SKILL_SAFE_BUILTINS = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "print": print, "range": range, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "sorted": sorted, "reversed": reversed,
    "isinstance": isinstance, "Exception": Exception,
    "TypeError": TypeError, "ValueError": ValueError,
}


def _scan_skill_ast(code: str, name: str) -> Optional[str]:
    """Scan skill code for dangerous patterns. Returns error string or None."""
    try:
        tree = _ast.parse(code, filename=f"<skill:{name}>")
    except SyntaxError as e:
        return f"Skill syntax error: {e}"

    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            return f"Skill cannot import modules"

        if isinstance(node, _ast.Attribute):
            if isinstance(node.attr, str) and node.attr in _SKILL_DANGEROUS_ATTRS:
                return f"Skill cannot access: {node.attr}"
            if node.attr == '__import__':
                return f"Skill cannot call __import__"

        if isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Name):
                if node.func.id in _SKILL_BLACKLIST:
                    return f"Skill cannot call: {node.func.id}"
            elif isinstance(node.func, _ast.Attribute):
                if isinstance(node.func.value, _ast.Name):
                    if node.func.value.id in _SKILL_BLACKLIST:
                        return f"Skill cannot call: {node.func.value.id}"
                    if node.func.attr in ('__import__', 'eval', 'exec', 'compile'):
                        return f"Skill cannot call: {node.func.value.id}.{node.func.attr}"

    return None


def _safe_exec_skill(code: str, name: str):
    """Execute a skill in a sandboxed environment."""
    error = _scan_skill_ast(code, name)
    if error:
        return error

    import math
    restricted = {
        "__builtins__": {
            **_SKILL_SAFE_BUILTINS,
            "True": True, "False": False, "None": None,
            "issubclass": issubclass,
        },
        "math": math,
    }
    local_ns = {}
    try:
        exec(compile(code, f"<skill:{name}>", "exec"), restricted, local_ns)
    except Exception as e:
        return f"Skill execution error: {e}"
    return local_ns
