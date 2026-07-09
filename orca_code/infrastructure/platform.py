"""orca_code.infrastructure.platform — Platform detection and initialization.

Extracted from config.py to separate platform concerns from configuration.
Handles Windows console setup (UTF-8, VT sequences), platform detection,
and environment information.
"""

from __future__ import annotations

import getpass
import os
import platform
import sys
from datetime import datetime
from pathlib import Path


def init_console() -> None:
    """Initialize console for UTF-8 and ANSI/VT support.

    On Windows: Set console code pages to UTF-8 and enable virtual terminal processing.
    On Unix: Reconfigure stdout/stderr for UTF-8 if needed.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)

            # Enable ANSI escape sequences (virtual terminal)
            STD_OUTPUT_HANDLE = -11
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        except Exception:
            pass

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def get_device_type() -> str:
    """Detect the device type from platform info."""
    system = platform.system()
    plat = platform.platform().lower()

    if system in ("Windows", "Darwin"):
        return "Desktop/Laptop"

    if system == "Linux":
        if "android" in plat:
            return "Phone"
        machine = platform.machine().lower()
        if any(machine.startswith(a) for a in ("armv7l", "armv6l", "aarch64", "arm64")):
            return "Mobile/Embedded"
        return "Desktop/Server"

    return "Unknown"


def get_system_info(working_dir: Path | None = None) -> str:
    """Generate a human-readable system information summary.

    Args:
        working_dir: Current working directory for disk usage info.

    Returns:
        Multi-line system info string.
    """
    now = datetime.now()
    lines = [
        f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})",
        f"User: {getpass.getuser()}",
        f"System: {platform.system()} ({platform.platform()})",
        f"Device: {get_device_type()}",
        f"Python: {platform.python_version()}",
    ]

    if working_dir:
        lines.append(f"Working Dir: {working_dir}")

    # Optional: CPU/Memory/Disk info via psutil
    try:
        import psutil
        cpu_phys = psutil.cpu_count(logical=False) or 0
        cpu_log = psutil.cpu_count(logical=True) or 0
        mem = psutil.virtual_memory()
        lines.extend([
            f"CPU: {cpu_phys} physical / {cpu_log} logical cores",
            f"Memory: {round(mem.total / 1024**3, 1)}GB total / {round(mem.available / 1024**3, 1)}GB available",
        ])
        if working_dir:
            try:
                disk = psutil.disk_usage(str(working_dir))
                lines.append(
                    f"Disk: {round(disk.total / 1024**3, 1)}GB total / {round(disk.free / 1024**3, 1)}GB free"
                )
            except Exception:
                pass
    except ImportError:
        pass

    return "\n".join(lines)


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def get_shell() -> str:
    """Get the preferred shell for command execution."""
    if sys.platform == "win32":
        return "powershell"
    return "bash"


# ═══════════════════════════════════════════════════════════════════════════════
# TerminalInfo — unified terminal capability detection
# ═══════════════════════════════════════════════════════════════════════════════

import enum as _enum


class TerminalFamily(_enum.Enum):
    """Broad terminal capability tier."""
    MODERN = "modern"    # Windows Terminal, VS Code, ConEmu, WezTerm, etc.
    LEGACY = "legacy"    # cmd.exe, PowerShell 5.x (limited ANSI/VT)
    UNKNOWN = "unknown"


class TerminalInfo:
    """Unified terminal detection for platform-appropriate rendering.

    Consolidates detection logic previously scattered across session_stream.py
    and session_ui.py.  Detection rules are identical to the original
    _terminal_supports_italic() logic.

    Usage:
        if TerminalInfo.is_legacy():
            ... use safe rendering ...
        cs = TerminalInfo.suggested_color_system()  # "truecolor" or "256"
        cols, rows = TerminalInfo.get_dimensions()
    """

    _family: TerminalFamily | None = None

    @classmethod
    def _detect(cls) -> TerminalFamily:
        """Detect terminal family once, cache result."""
        if sys.platform != "win32":
            return TerminalFamily.MODERN

        # Windows Terminal (modern, full ANSI/VT support)
        if os.environ.get("WT_SESSION"):
            return TerminalFamily.MODERN

        # VS Code / Cursor integrated terminal
        term_program = os.environ.get("TERM_PROGRAM", "").lower()
        if term_program in ("vscode", "cursor"):
            return TerminalFamily.MODERN

        # ConEmu / Cmder
        if os.environ.get("ConEmuPID") or "ConEmu" in os.environ.get("TERM_PROGRAM", ""):
            return TerminalFamily.MODERN

        # WezTerm, Alacritty, Tabby, Warp — modern GPU-accelerated terminals
        if term_program in ("wezterm", "alacritty", "tabby", "warp"):
            return TerminalFamily.MODERN

        # Everything else on Windows: cmd.exe, PowerShell 5.x, etc.
        return TerminalFamily.LEGACY

    @classmethod
    def family(cls) -> TerminalFamily:
        """Get the detected terminal family (cached)."""
        if cls._family is None:
            cls._family = cls._detect()
        return cls._family

    @classmethod
    def is_legacy(cls) -> bool:
        """True on cmd.exe, old PowerShell 5.x — limited ANSI/VT support."""
        return cls.family() == TerminalFamily.LEGACY

    @classmethod
    def is_modern(cls) -> bool:
        """True on Windows Terminal, VS Code, ConEmu, WezTerm, Unix terminals."""
        return cls.family() == TerminalFamily.MODERN

    @classmethod
    def supports_italic(cls) -> bool:
        """True if the terminal supports ANSI SGR italic [3m and dim [2m.

        Legacy Windows terminals (cmd.exe, old PowerShell 5.x) lack italic/dim
        support. When they encounter unsupported SGR codes, their ANSI state
        machine corrupts — the codes are silently ignored but the state tracker
        doesn't account for them, so subsequent \\033[0m loses sync.
        """
        return cls.is_modern()

    @classmethod
    def suggested_color_system(cls) -> str:
        """Return the recommended Rich color_system for this terminal.

        Legacy terminals (cmd.exe) get "256" (8-bit color) to avoid truecolor
        ANSI codes that can desync their VT parser.  Modern terminals get
        "truecolor" for full 24-bit color fidelity.
        """
        return "truecolor" if cls.is_modern() else "256"

    @classmethod
    def get_dimensions(cls) -> tuple[int, int]:
        """Get current terminal (columns, rows).  Safe wrapper.

        Returns (80, 24) on any error — a reasonable fallback.
        """
        try:
            size = os.get_terminal_size()
            return (size.columns, size.lines)
        except Exception:
            return (80, 24)

    @classmethod
    def invalidate(cls) -> None:
        """Clear the cached terminal family so next family() re-detects.

        Useful after the terminal emulator changes (e.g. user switches from
        cmd.exe to Windows Terminal mid-session — rare, but supported).
        """
        cls._family = None
