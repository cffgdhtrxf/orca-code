"""orca_code.infrastructure.platform — Platform detection and initialization.

Extracted from config.py to separate platform concerns from configuration.
Handles Windows console setup (UTF-8, VT sequences), platform detection,
and environment information.
"""

from __future__ import annotations

import getpass
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
