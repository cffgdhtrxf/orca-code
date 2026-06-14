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

import ast as _ast
import ipaddress
import re
import urllib.parse

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

    # ── Windows-specific always-blocked patterns ──
    # Recursive/forced deletion of entire drives
    (r'(?i)\bdel\s+/[sfq]\s+[A-Z]:\\', "Windows recursive drive delete (del /s /f C:\\)"),
    (r'(?i)\brmdir\s+/[sq]\s+[A-Z]:\\', "Windows recursive drive removal (rmdir /s C:\\)"),
    (r'(?i)\b(rd|rmdir)\s+/s\s+/q\s+%[A-Z_]+%', "Windows recursive env-var removal"),
    # Format command
    (r'(?i)\bformat\s+[A-Z]:\s*/', "Windows drive format (format C: /q)"),
    # Diskpart (can destroy partitions)
    (r'(?i)\bdiskpart\b.*\b(clean|delete|format)\b', "DiskPart destructive operation"),
    # Registry deletion
    (r'(?i)\breg\s+delete\s+HKLM', "Windows registry deletion (HKLM)"),
    (r'(?i)\breg\s+delete\s+/f\s+HK', "Windows registry forced deletion"),
    # BCDEdit tampering
    (r'(?i)\bbcdedit\s+/delete', "Windows boot configuration deletion"),
    # WMIC destructive
    (r'(?i)\bwmic\s+.*\bdelete\b', "WMIC delete operation"),
    # Schtasks persistence
    (r'(?i)\bschtasks\s+/create\s+/sc\s+onstart', "Scheduled task persistence"),
    # Network exfiltration to common paste / file-drop sites
    (r'(?i)\b(nc|netcat|ncat)\b.*-e\s', "Netcat reverse shell (-e flag)"),

    # ── Linux specific always-blocked ──
    # echo to kernel params
    (r'(?i)\becho\s+.*>\s*/proc/sys/', "Writing to kernel parameters"),
    # chattr immutable
    (r'(?i)\bchattr\s+\+i\s+/', "Filesystem attribute tampering (chattr +i /)"),
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

    # Windows: write to system directories
    (r'(?i)\b(copy|move|xcopy|robocopy)\s+.*%windir%', "Windows system directory write"),
    (r'(?i)\b(copy|move|xcopy|robocopy)\s+.*C:\\Windows', "Windows system directory write"),
    (r'(?i)\b(copy|move|xcopy|robocopy)\s+.*Program Files', "Program Files write"),

    # Package managers (can install/replace system packages)
    (r'(?i)\b(apt-get|apt|yum|dnf|pacman|zypper)\s+install\b', "Package manager install"),
    (r'(?i)\b(pip|npm|cargo)\s+install\s+-g\b', "Global package install (requires root)"),

    # Docker privileged
    (r'(?i)\bdocker\s+run\s+.*--privileged\b', "Docker privileged container"),
    (r'(?i)\bdocker\s+run\s+.*-v\s+/:/', "Docker mount root filesystem"),

    # Download + execute patterns
    (r'(?i)\b(iwr|Invoke-WebRequest)\s+.*\|\s*iex\b', "PowerShell download + execute (IWR|IEX)"),
    (r'(?i)\bwget\s+.*-O\s+-\s*\|\s*(ba)?sh\b', "wget pipe to shell"),
]


def check_command_safety(command: str, yolo: bool = False) -> tuple[bool, str]:
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


# ═══════════════════════════════════════════════════════════════════════════════
# Two-Dimensional Command Whitelist
# Mode × CommandType — restricts which commands are allowed based on
# permission mode and the command's risk category.
# ═══════════════════════════════════════════════════════════════════════════════

# Read-only safe commands (data viewing, no mutation)
_READ_SAFE_COMMANDS = {
    # Unix
    "ls", "cat", "head", "tail", "less", "file", "stat",
    "find", "grep", "rg", "wc", "sort", "uniq", "cut", "tr",
    "pwd", "whoami", "id", "groups", "env", "printenv",
    "date", "uptime", "uname", "hostname", "which", "whereis",
    "git", "hg", "du", "df", "awk", "sed",  # sed/awk are read-only by default
    "diff", "cmp", "comm", "xxd", "hexdump",
    # Windows
    "dir", "type", "echo", "ver", "time",
    "where", "systeminfo",
    "tasklist", "net", "ipconfig", "ping", "tracert", "nslookup",
    "findstr", "fc", "comp", "tree",
    # Common
    "python", "python3", "node", "npm", "npx",  # used for --version/--help
    "pip", "cargo", "rustc", "go", "java", "javac",
    "make", "cmake", "ninja", "meson",
    "docker", "kubectl", "helm", "terraform",
}

# Write-safe commands (data-mutating but not system-destroying)
_WRITE_SAFE_COMMANDS = {
    "mkdir", "touch", "cp", "mv", "rm", "rmdir",
    "tar", "gzip", "zip", "unzip", "7z", "rar",
    "chmod", "chown", "chgrp",
    "ln", "readlink", "realpath",
    "mount", "umount",
    # Windows
    "copy", "move", "del", "erase", "rename", "ren",
    "md", "rd", "mklink",
    "xcopy", "robocopy",
    "attrib", "icacls", "takeown",
    # Package managers
    "pip", "npm", "cargo", "gem", "composer",
    # Version control write ops
    "git",
    # Editors
    "nano", "vim", "vi", "emacs", "code", "notepad",
}


def check_mode_command(command: str, permission_mode) -> tuple[bool, str]:
    """Check if a command is allowed under the current permission mode.

    This is an ADDITIONAL check on top of the safety net. The safety net
    (check_command_safety) always runs first. This check runs second and
    determines whether the command fits the current permission mode.

    Args:
        command: The shell command to check.
        permission_mode: PermissionMode enum value.

    Returns:
        (is_allowed: bool, reason: str)
    """
    from orca_code.permissions import PermissionMode

    # YOLO mode: anything goes (safety net still applies upstream)
    if permission_mode == PermissionMode.YOLO:
        return True, ""

    # Extract base command
    try:
        import shlex
        parts = shlex.split(command, posix=(__import__('sys').platform != "win32"))
        if not parts:
            return True, ""
        base_cmd = __import__('pathlib').Path(parts[0]).name.lower()
    except Exception:
        return True, ""

    # Strip common suffixes
    for suffix in (".exe", ".cmd", ".bat", ".com", ".ps1"):
        if base_cmd.endswith(suffix):
            base_cmd = base_cmd[:-len(suffix)]

    # READ_ONLY mode: only _READ_SAFE_COMMANDS
    if permission_mode == PermissionMode.READ_ONLY:
        if base_cmd in _READ_SAFE_COMMANDS:
            return True, ""
        return False, (
            f"Command '{base_cmd}' not allowed in read-only mode.\n"
            f"Allowed commands include: "
            f"{', '.join(sorted(list(_READ_SAFE_COMMANDS)[:20]))}..."
        )

    # AUTO mode: READ + WRITE safe commands
    if permission_mode == PermissionMode.AUTO:
        if base_cmd in _READ_SAFE_COMMANDS or base_cmd in _WRITE_SAFE_COMMANDS:
            return True, ""
        return False, (
            f"Command '{base_cmd}' requires explicit permission in auto mode.\n"
            f"Use YOLO mode to allow all commands: /permissions mode yolo"
        )

    return True, ""


def is_safe_url(url: str) -> tuple[bool, str]:
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


def _scan_skill_ast(code: str, name: str) -> str | None:
    """Scan skill code for dangerous patterns. Returns error string or None."""
    try:
        tree = _ast.parse(code, filename=f"<skill:{name}>")
    except SyntaxError as e:
        return f"Skill syntax error: {e}"

    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            return "Skill cannot import modules"

        if isinstance(node, _ast.Attribute):
            if isinstance(node.attr, str) and node.attr in _SKILL_DANGEROUS_ATTRS:
                return f"Skill cannot access: {node.attr}"
            if node.attr == '__import__':
                return "Skill cannot call __import__"

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
