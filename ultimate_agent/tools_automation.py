
import os, sys, subprocess, shutil, threading, time
from pathlib import Path
from typing import Optional, Dict
from ultimate_agent.config import (CONFIG, ENABLE_GUI_AUTO,
    ENABLE_BROWSER_AUTO, TEMP_DIR, OUTPUT_DIR, ensure_pkg, console)
from ultimate_agent.security import _is_safe_url

"""ultimate_agent.tools_automation — GUI + browser automation."""


def _gui_confirm(action: str, detail: str) -> bool:
    if not ENABLE_GUI_AUTO:
        return False
    return True
def gui_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    if not _gui_confirm("鼠标点击", f"坐标: ({x}, {y}), 按钮: {button}, 次数: {clicks}"):
        return "操作已取消（用户未确认或超时）"
    try:
        import pyautogui
    except ImportError:
        if ensure_pkg("pyautogui"):
            import pyautogui
        else:
            return "错误: 缺少 pyautogui (pip install pyautogui)"
    try:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"已在 ({x}, {y}) 执行 {button} 键 {clicks} 次点击"
    except Exception as e:
        return f"错误: {e}"

def gui_type(text: str, interval: float = 0.01) -> str:
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    _hotkey_patterns = ['{win}', '{ctrl}', '{alt}', '{shift}', '+s', '+r', '+e', '+d', '+l', '+tab']
    if any(p in text.lower() for p in _hotkey_patterns):
        return ("错误: gui_type 只能输入纯文本，不能发送快捷键。"
                "请使用 gui_hotkey 工具，例如 gui_hotkey(keys=['win','s']) 打开搜索。")
    # Clipboard + Ctrl+V: only method that works on both Win32 and UWP
    if not ensure_pkg("pyperclip"):
        return "错误: 缺少 pyperclip (pip install pyperclip)"
    if not ensure_pkg("pyautogui"):
        return "错误: 缺少 pyautogui (pip install pyautogui)"
    import pyperclip, pyautogui
    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(len(text) * 0.02 + 0.1)
        return f"已粘贴 {len(text)} 个字符"
    except Exception as e:
        return f"错误: {e}"

def gui_press(key: str) -> str:
    """Press a single key like enter, tab, escape, backspace. For combo keys use gui_hotkey."""
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    if not ensure_pkg("pyautogui"):
        return "错误: 缺少 pyautogui (pip install pyautogui)"
    import pyautogui
    try:
        pyautogui.press(key)
        return f"已按键: {key}"
    except Exception as e:
        return f"错误: {e}"

def gui_hotkey(keys: list) -> str:
    """Send a keyboard shortcut / hotkey combination. Example: gui_hotkey(keys=['win','s']) for Win+S."""
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    key_display = " + ".join(str(k).title() for k in keys)
    if not _gui_confirm("组合键", f"热键: {key_display}"):
        return "操作已取消（用户未确认或超时）"
    try:
        import pyautogui
    except ImportError:
        if ensure_pkg("pyautogui"):
            import pyautogui
        else:
            return "错误: 缺少 pyautogui (pip install pyautogui)"
    try:
        pyautogui.hotkey(*keys)
        return f"已发送组合键: {key_display}"
    except Exception as e:
        return f"错误: {e}"

def gui_move(x: int, y: int, duration: float = 0.5) -> str:
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    try:
        import pyautogui
    except ImportError:
        if ensure_pkg("pyautogui"):
            import pyautogui
        else:
            return "错误: 缺少 pyautogui (pip install pyautogui)"
    try:
        pyautogui.moveTo(x, y, duration=duration)
        return f"鼠标已移动到 ({x}, {y})"
    except Exception as e:
        return f"错误: {e}"

def window_focus(title: str) -> str:
    """Find a window by title (partial match) and bring it to foreground."""
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    try:
        import pygetwindow as gw
    except ImportError:
        if ensure_pkg("pygetwindow"):
            import pygetwindow as gw
        else:
            return "错误: 缺少 pygetwindow (pip install pygetwindow)"
    try:
        matches = [w for w in gw.getWindowsWithTitle(title) if w.title]
        if not matches:
            return f"错误: 未找到标题包含 '{title}' 的窗口"
        w = matches[0]
        w.activate()
        time.sleep(0.2)
        return f"已激活窗口: {w.title} @ ({w.left},{w.top}) {w.width}x{w.height}"
    except Exception as e:
        return f"错误: {e}"

def find_on_screen(description: str) -> str:
    """Screenshot → OCR → find text/button coordinates. Returns positions of matching UI elements."""
    if not ENABLE_GUI_AUTO:
        return "错误: GUI 自动化未启用（enable_gui_auto: false）"
    try:
        import mss, pyautogui
    except ImportError:
        if ensure_pkg("mss"):
            import mss, pyautogui
        else:
            return "错误: 缺少 mss (pip install mss)"
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        if ensure_pkg("rapidocr-onnxruntime", "rapidocr_onnxruntime"):
            from rapidocr_onnxruntime import RapidOCR
        else:
            return "错误: 缺少 rapidocr-onnxruntime"
    try:
        # Take screenshot
        screen_w, screen_h = pyautogui.size()
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[1])
            tmp_path = str(OUTPUT_DIR / "_find_tmp.png")
            mss.tools.to_png(img.rgb, img.size, output=tmp_path)
        # OCR with position data
        engine = RapidOCR()
        result, _ = engine(tmp_path)
        if not result:
            return "未识别到任何文字"
        # Filter by description
        kw = description.lower()
        lines = []
        for box, text, score in result:
            if score < 0.5:
                continue
            x1, y1, x2, y2 = int(box[0][0]), int(box[0][1]), int(box[2][0]), int(box[2][1])
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            lines.append(f"{text} → 中心({cx},{cy}) 区域({x1},{y1})-({x2},{y2}) 置信度{score:.0%}")
        if not lines:
            return f"未找到匹配 '{description}' 的文字"
        return "\n".join(lines[:30])
    except Exception as e:
        return f"错误: {e}"

_browser_lock = threading.Lock()
def _get_browser() -> Optional[Dict]:
    with _browser_lock:
        return _browser_instance
def browser_open(url: str, headless: bool = False) -> str:
    safe, reason = _is_safe_url(url)
    if not safe:
        return f"错误: {reason}"
    if not ENABLE_BROWSER_AUTO:
        # Fallback: open with system default browser via start command (Windows) / open (macOS) / xdg-open (Linux)
        try:
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "start", "", url], shell=False,
                               capture_output=True, timeout=10)
            elif sys.platform == "darwin":
                subprocess.run(["open", url], capture_output=True, timeout=10)
            else:
                subprocess.run(["xdg-open", url], capture_output=True, timeout=10)
            return f"已用系统浏览器打开: {url}"
        except Exception as e:
            return f"错误: 无法打开浏览器 — {e}"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if ensure_pkg("playwright"):
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True, timeout=300
                )
            except Exception:
                pass
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                return "错误: Playwright 安装失败，请手动执行: pip install playwright && playwright install chromium"
        else:
            return "错误: 缺少 playwright (pip install playwright && playwright install chromium)"

    try:
        global _browser_instance
        # Fast path: browser already running
        with _browser_lock:
            if _browser_instance:
                _browser_instance["page"].goto(url, wait_until="domcontentloaded", timeout=15000)
                return f"已在现有浏览器中打开: {url}"

        # Slow path: initialize Playwright outside lock to avoid long hold
        p = sync_playwright().start()
        user_data_dir = TEMP_DIR / f"browser_profile_{int(time.time())}"
        context = p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=headless,
            args=["--no-first-run", "--no-default-browser-check"]
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=15000)

        # Double-check under lock
        with _browser_lock:
            if _browser_instance:
                # Another thread beat us, close our duplicate
                context.close()
                p.stop()
                shutil.rmtree(str(user_data_dir), ignore_errors=True)
                _browser_instance["page"].goto(url, wait_until="domcontentloaded", timeout=15000)
                return f"已在现有浏览器中打开: {url}"
            _browser_instance = {"playwright": p, "context": context, "page": page, "profile": user_data_dir}
        return f"已打开浏览器（临时 Profile）: {url}"
    except Exception as e:
        # [FIX] Clean up any partially-created browser resources
        for var in ('context', 'page'):
            obj = locals().get(var)
            if obj:
                try: obj.close()
                except Exception: pass
        playwright_obj = locals().get('p')
        if playwright_obj:
            try: playwright_obj.stop()
            except Exception: pass
        user_dir = locals().get('user_data_dir')
        if user_dir:
            try: shutil.rmtree(str(user_dir), ignore_errors=True)
            except Exception: pass
        return f"错误: 浏览器打开失败 - {e}"
def browser_click(selector: str) -> str:
    if not ENABLE_BROWSER_AUTO:
        return "错误: 浏览器自动化未启用"
    inst = _get_browser()
    if not inst:
        return "错误: 浏览器未打开，请先调用 browser_open"
    try:
        inst["page"].click(selector, timeout=10000)
        return f"已点击元素: {selector}"
    except Exception as e:
        return f"错误: {e}"
def browser_type(selector: str, text: str) -> str:
    if not ENABLE_BROWSER_AUTO:
        return "错误: 浏览器自动化未启用"
    inst = _get_browser()
    if not inst:
        return "错误: 浏览器未打开，请先调用 browser_open"
    try:
        inst["page"].fill(selector, text, timeout=10000)
        return f"已在 {selector} 输入文本"
    except Exception as e:
        return f"错误: {e}"
def browser_screenshot(output_path: str = None) -> str:
    if not ENABLE_BROWSER_AUTO:
        return "错误: 浏览器自动化未启用"
    inst = _get_browser()
    if not inst:
        return "错误: 浏览器未打开，请先调用 browser_open"
    try:
        p = Path(output_path) if output_path else TEMP_DIR / "browser_screenshot.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        inst["page"].screenshot(path=str(p), full_page=True)
        return f"已保存浏览器截图: {p}"
    except Exception as e:
        return f"错误: {e}"
def browser_close() -> str:
    global _browser_instance
    if not _browser_instance:
        return "浏览器未运行"
    try:
        _browser_instance["context"].close()
        _browser_instance["playwright"].stop()
        profile = _browser_instance.get("profile")
        if profile and Path(profile).exists():
            shutil.rmtree(str(profile), ignore_errors=True)
        return "浏览器已关闭并清理临时 Profile"
    except Exception as e:
        return f"错误: {e}"
    finally:
        with _browser_lock:
            _browser_instance = None