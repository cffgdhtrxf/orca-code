"""
tray_app.py — System tray launcher for Orca Code.
Right-click tray icon to start/stop the agent.
Win+Shift+A global hotkey to toggle visibility.

Features:
  - Start/Stop agent from tray menu
  - Auto-start with Windows (toggle via tray menu)
  - Open Dashboard in browser
  - Update check notification
  - Win+Shift+A global hotkey
"""
import sys
import os
import subprocess
import threading
import webbrowser
import ctypes
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    print("[提示] 系统托盘需要: pip install pystray Pillow")
    print("[提示] 直接启动 Orca Code...")
    subprocess.run([sys.executable, str(SCRIPT_DIR / "orca_code.py")])
    sys.exit(0)

# ---- Global state ----
_agent_process = None
_agent_lock = threading.Lock()
_icon_ref = None  # For notifications from background threads

# ---- Console window helpers ----
def _get_console_window():
    """Find the console window of the agent process."""
    windows = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def _enum(hwnd, _):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                if "Orca" in buff.value:
                    pid = ctypes.c_ulong()
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if _agent_process and pid.value == _agent_process.pid:
                        windows.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_enum), 0)
    return windows[0] if windows else None


def _show_console():
    hwnd = _get_console_window()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)


def _hide_console():
    hwnd = _get_console_window()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE


# ---- Icon ----
def _create_icon():
    """Create a simple 32x32 AI icon."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Purple circle
    draw.ellipse([2, 2, 30, 30], fill="#7C3AED", outline="#6D28D9", width=2)
    # "AI" text
    draw.text((7, 8), "AI", fill="white")
    return img


# ---- Agent process management ----
def start_agent():
    global _agent_process
    with _agent_lock:
        if _agent_process and _agent_process.poll() is None:
            _show_console()
            return "Agent already running"
        try:
            creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
            _agent_process = subprocess.Popen(
                [sys.executable, str(SCRIPT_DIR / "orca_code.py")],
                cwd=str(SCRIPT_DIR),
                creationflags=creationflags,
            )
            return "Agent started"
        except Exception as e:
            return f"Failed: {e}"


def stop_agent():
    global _agent_process
    with _agent_lock:
        if _agent_process and _agent_process.poll() is None:
            _agent_process.terminate()
            try:
                _agent_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _agent_process.kill()
            return "Agent stopped"
        return "Agent not running"


def toggle_agent():
    global _agent_process
    if _agent_process and _agent_process.poll() is None:
        stop_agent()
    else:
        start_agent()


# ---- Auto-start with Windows ----
_AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "OrcaCode"


def _is_autostart_enabled() -> bool:
    """Check if auto-start with Windows is enabled."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, _AUTOSTART_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _toggle_autostart(enable: bool):
    """Enable or disable auto-start with Windows."""
    if sys.platform != "win32":
        return
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            tray_path = str(SCRIPT_DIR / "tray_app.py")
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ,
                              f'"{sys.executable}" "{tray_path}"')
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


# ---- Update check (background) ----
def _check_update_background(icon):
    """Check for updates in a background thread, notify if available."""
    try:
        from orca_code.infrastructure.updater import check_for_update
        info = check_for_update()
        if info:
            icon.notify(
                f"Orca Code v{info['version']} available!\n"
                f"Current: v{info['current_version']}\n"
                f"Run `orca --update` to upgrade.",
                "Update Available"
            )
    except Exception:
        pass


# ---- Tray menu callbacks ----
def _on_start(icon, item):
    msg = start_agent()
    icon.notify(msg, "Orca Code")


def _on_stop(icon, item):
    msg = stop_agent()
    icon.notify(msg, "Orca Code")


def _on_toggle(icon, item):
    toggle_agent()


def _on_dashboard(icon, item):
    """Open the web Dashboard in the default browser."""
    webbrowser.open("http://localhost:8499")


def _on_autostart(icon, item):
    """Toggle auto-start with Windows."""
    current = _is_autostart_enabled()
    _toggle_autostart(not current)
    state = "enabled" if not current else "disabled"
    icon.notify(f"Auto-start {state}", "Orca Code")


def _on_check_update(icon, item):
    """Manually check for updates."""
    threading.Thread(target=_check_update_background, args=(icon,), daemon=True).start()
    icon.notify("Checking for updates...", "Orca Code")


def _on_exit(icon, item):
    stop_agent()
    icon.stop()


# ---- Hotkey ----
def _setup_hotkey():
    """Register Win+Shift+A global hotkey."""
    try:
        MOD_ALT = 0x0001
        MOD_WIN = 0x0008
        MOD_NOREPEAT = 0x4000
        VK_A = 0x41
        HOTKEY_ID = 1

        if not ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, MOD_WIN | MOD_NOREPEAT, VK_A):
            return False

        def _poll():
            msg = ctypes.wintypes.MSG()
            while True:
                if ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        toggle_agent()
                    ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                    ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    break

        threading.Thread(target=_poll, daemon=True).start()
        return True
    except Exception:
        return False


# ---- Main ----
def main():
    global _icon_ref
    print("Starting Orca Code tray app...")

    # Auto-start agent on launch
    start_agent()

    # Setup hotkey
    _setup_hotkey()

    # Build autostart menu item with checkmark
    autostart_enabled = _is_autostart_enabled()
    autostart_label = f"{'✓' if autostart_enabled else '○'} Auto-start with Windows"

    # Create tray icon
    icon = pystray.Icon(
        "orca_code",
        _create_icon(),
        "Orca Code",
        menu=pystray.Menu(
            pystray.MenuItem("Start Agent", _on_start),
            pystray.MenuItem("Stop Agent", _on_stop),
            pystray.MenuItem("Toggle (Win+Shift+A)", _on_toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Dashboard", _on_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(autostart_label, _on_autostart),
            pystray.MenuItem("Check for Updates", _on_check_update),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", _on_exit),
        ),
    )
    _icon_ref = icon

    # Background update check (5 min after startup, to not block launch)
    threading.Timer(300, _check_update_background, args=[icon]).start()

    icon.run()


if __name__ == "__main__":
    main()
