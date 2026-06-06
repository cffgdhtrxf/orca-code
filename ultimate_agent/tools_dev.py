"""ultimate_agent.tools_dev — Git, code nav, vision, Python REPL."""

import os, sys, re, base64, time, tempfile, subprocess
from pathlib import Path
from datetime import datetime
import openai
from openai import OpenAI
from ultimate_agent.config import (CONFIG, MODEL, BASE_URL, API_KEY,
    IS_MULTIMODAL, VISION_MODEL, VISION_BASE_URL, VISION_API_KEY,
    WORKING_DIR, TEMP_DIR, OUTPUT_DIR, HAS_OPENCV, HAS_PILLOW, client, console)

# Lazy imports for optional deps (HAS_* flags checked before use)
try:
    import cv2
except ImportError:
    cv2 = None
try:
    from PIL import Image, ImageGrab
except ImportError:
    Image = ImageGrab = None

def _run_git(args: list, cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not a git repository" in stderr.lower():
                return f"错误: {cwd} 不是 Git 仓库"
            return f"错误: {stderr}"
        return result.stdout.strip()[:8000]
    except FileNotFoundError:
        return "错误: git 未安装或不在 PATH 中"
    except subprocess.TimeoutExpired:
        return "错误: git 命令超时（30秒）"
    except Exception as e:
        return f"错误: {e}"
def git_status(repo_path: str = None) -> str:
    cwd = repo_path or WORKING_DIR
    output = _run_git(["status", "--short"], cwd)
    if not output or output.startswith("错误"):
        return output or "工作区干净（无变更）"
    return output
def git_diff(repo_path: str = None, staged: bool = False) -> str:
    cwd = repo_path or WORKING_DIR
    args = ["diff", "--staged"] if staged else ["diff"]
    return _run_git(args, cwd)
def git_log(repo_path: str = None, max_count: int = 20) -> str:
    cwd = repo_path or WORKING_DIR
    n = max(min(max_count, 100), 1)
    return _run_git(["log", f"--max-count={n}", "--oneline", "--decorate", "--graph"], cwd)
def git_blame(repo_path: str = None, file: str = None) -> str:
    cwd = repo_path or WORKING_DIR
    return _run_git(["blame", file], cwd)
def _extract_symbol(file_path: str, line: int, column: int) -> str:
    try:
        lines = Path(file_path).read_text(errors="replace").splitlines()
        if line < 1 or line > len(lines):
            return ""
        text = lines[line - 1]
        if column < 1 or column > len(text):
            return ""
        start = column - 1
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == '_'):
            start -= 1
        end = column - 1
        while end < len(text) and (text[end].isalnum() or text[end] == '_'):
            end += 1
        return text[start:end] if end > start else ""
    except Exception:
        return ""
def go_to_definition(file_path: str, line: int = 0, column: int = 0, symbol: str = None) -> str:
    p = Path(file_path)
    if not p.exists():
        return f"错误: 文件不存在 - {file_path}"
    try:
        if not symbol:
            symbol = _extract_symbol(file_path, line, column)
        if not symbol or not symbol.strip():
            return f"错误: 无法识别第 {line} 行的符号"
        patterns = [
            rf'^\s*(?:async\s+)?def\s+{re.escape(symbol)}\s*\(',
            rf'^\s*class\s+{re.escape(symbol)}\s*(?::|\(|\b)',
            rf'^\s*{re.escape(symbol)}\s*=\s*(?:lambda|class|\(|\")',
            rf'^\s*{re.escape(symbol)}\s*:\s*(?:int|str|float|bool|list|dict|set|tuple|Any|Optional|Union)',
        ]
        results = []
        for i, line_text in enumerate(p.read_text(errors="replace").splitlines(), 1):
            for pat in patterns:
                if re.match(pat, line_text):
                    results.append(f"{file_path}:{i}:\n  {line_text.strip()}")
                    break
        if not results:
            for py_file in sorted(p.parent.glob("*.py")):
                if py_file.name == p.name:
                    continue
                for i, l in enumerate(py_file.read_text(errors="replace").splitlines(), 1):
                    for pat in patterns:
                        if re.match(pat, l):
                            results.append(f"{py_file}:{i}:\n  {l.strip()}")
                            break
        return "\n".join(results) if results else f"未找到 '{symbol}' 的定义"
    except Exception as e:
        return f"错误: {e}"
def find_references(symbol: str, directory: str = None, file_filter: str = None) -> str:
    base = Path(directory) if directory else Path(WORKING_DIR)
    pattern = file_filter or "*.py"
    regex = re.compile(rf'\b{re.escape(symbol)}\b')
    results = []
    for f in base.rglob(pattern):
        if not f.is_file() or f.stat().st_size > 1024 * 1024:
            continue
        try:
            for i, line_text in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if regex.search(line_text):
                    results.append(f"{f.relative_to(base)}:{i}: {line_text.strip()[:200]}")
                    if len(results) >= 50:
                        break
        except Exception:
            continue
        if len(results) >= 50:
            break
    return "\n".join(results) if results else f"未找到 '{symbol}' 的引用"
def analyze_image(image_path: str, question: str = None) -> str:
    """Analyze image. Multimodal models see images directly; others use vision_model."""
    import base64
    p = Path(image_path)
    if not p.exists():
        return f"Error: image not found - {image_path}"
    valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    if p.suffix.lower() not in valid_extensions:
        return f"Error: unsupported format {p.suffix}, supported: {', '.join(valid_extensions)}"
    if p.stat().st_size > 10 * 1024 * 1024:
        return f"Error: image too large (>10MB)"

    with open(p, "rb") as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')
    mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp'}
    mime_type = mime_map.get(p.suffix.lower(), 'image/jpeg')
    data_uri = f"data:{mime_type};base64,{image_data}"

    # Multimodal: embed image directly in conversation, main model sees it
    if IS_MULTIMODAL:
        return f"__IMAGE__:{data_uri}"

    # Non-multimodal: call vision model separately
    vision_model = VISION_MODEL or MODEL
    # Use vision-specific client if configured, otherwise main client
    if VISION_BASE_URL != BASE_URL or VISION_API_KEY != API_KEY:
        vision_client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL,
                               timeout=openai.Timeout(300.0, connect=10.0))
    else:
        vision_client = client
    try:
        user_content = [
            {"type": "text", "text": question or "Please describe this image in detail"},
            {"type": "image_url", "image_url": {"url": data_uri}}
        ]
        response = vision_client.chat.completions.create(
            model=vision_model,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=1000, temperature=0.7,
            timeout=60.0,
        )
        result = response.choices[0].message.content
        return result if result else "Error: image analysis returned empty response"
    except openai.BadRequestError:
        return (f"Error: model '{vision_model}' does not support vision. "
                f"Set vision_model in config.json to a multimodal model.")
    except Exception as e:
        return f"Error: image analysis failed - {e}"
def capture_camera(camera_index: int = 0, question: str = None) -> str:
    """从摄像头捕获图像并分析，同时用系统图片查看器打开照片"""
    if not HAS_OPENCV:
        return "错误: 未安装 opencv-python，请运行: pip install opencv-python"
    
    cap = None
    
    try:
        # 打开摄像头
        print("\n[提示] 正在打开摄像头...")
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            return f"错误: 无法打开摄像头 {camera_index}"
        
        # 多尝试几次以确保获取到有效帧
        frame = None
        for attempt in range(5):
            ret, frame = cap.read()
            if ret and frame is not None:
                break
            time.sleep(0.2)
        
        if not ret or frame is None:
            return "错误: 无法从摄像头捕获图像用于分析"
        
        # 保存到 output/ 工作区
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        camera_path = str(OUTPUT_DIR / f"camera_{timestamp}.jpg")
        
        # OpenCV 使用 BGR，需要转换为 RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        from PIL import Image
        img = Image.fromarray(frame_rgb)
        img.save(camera_path, "JPEG", quality=85)
        
        print(f"[提示] 照片已保存: {camera_path}")
        
        # 释放摄像头
        cap.release()
        cap = None
        
        # 用系统默认图片查看器打开照片
        print("[提示] 正在用系统图片查看器打开照片...")
        try:
            if sys.platform == "win32":
                os.startfile(camera_path)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", camera_path])
            else:  # Linux
                subprocess.run(["xdg-open", camera_path])
            print("[提示] 照片已在图片查看器中打开")
        except Exception as e:
            print(f"[警告] 无法自动打开图片: {e}")
            print(f"[提示] 请手动打开: {camera_path}")
        
        # Multimodal: return image directly; non-multimodal: call vision model
        if IS_MULTIMODAL:
            print("[提示] 多模态模式，图像直接交给主模型...")
            return analyze_image(camera_path, question or "Please describe what you see")
        else:
            print("[提示] 正在进行 AI 分析...")
            result = analyze_image(camera_path, question or "请描述摄像头画面中的内容")
            print("[提示] 分析完成")
            return result
        
    except Exception as e:
        return f"错误: 摄像头捕获失败 - {e}"
    finally:
        if cap is not None:
            try:
                cap.release()
            except:
                pass