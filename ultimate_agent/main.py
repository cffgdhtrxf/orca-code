"""ultimate_agent.main — Tool registry, user input, main loop."""

import os, sys, json, re, time, unicodedata, inspect
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from ultimate_agent.config import (CONFIG, SCRIPT_DIR, SAVE_DIR, TEMP_DIR,
    SKILLS_DIR, WORKING_DIR, HAS_MEMORY, HAS_SPEECH_RECOGNITION,
    ENABLE_VOICE, ENABLE_TTS, HAS_TTS, SPEECH_BACKEND,
    ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO,
    IS_MULTIMODAL, MODEL, BASE_URL, API_KEY, TERM_WIDTH,
    mem_mgr, console, client, mask_key, get_api_balance,
    handle_config_cmd, handle_profile_cmd)
from ultimate_agent.tools_core import *
from ultimate_agent.tools_office import *
from ultimate_agent.tools_web import *
from ultimate_agent.tools_dev import *
from ultimate_agent.tools_skills import *
from ultimate_agent.tools_skills import (_loaded_skills, _md_skill_cache,
    _autoload_skills_cache, _parse_skill_md, _scheduler_shutdown, _scheduler_thread)
from ultimate_agent.tools_automation import *
from ultimate_agent.tts_mcp import (speak_text, voice_input, init_mcp_tools,
    init_speech_recognition)
from ultimate_agent.session import *
from ultimate_agent.session import _msg_tokens
from ultimate_agent.utils import (_estimate_tokens, cleanup_temp_files, resolve_tool_path)

try:
    from _memory_manager import MemoryManager
except ImportError:
    MemoryManager = None
try:
    from _python_repl import execute_python
    HAS_PYTHON_REPL = True
except ImportError:
    HAS_PYTHON_REPL = False
    def execute_python(code, timeout=30): return "REPL not available"

def update_profile(note: str) -> str:
    """Add a note to the user profile. Use when you learn something about the user:
    preferences, coding habits, projects they work on, tools they use,
    how they like answers formatted (concise/detailed, Chinese/English, code style).
    The profile is injected into the system prompt every session."""
    if not HAS_MEMORY or not mem_mgr:
        return "Profile system not available."
    try:
        existing = mem_mgr.get_meta("user_profile") or ""
        existing += f" {note.strip()}"
        # Keep under 500 chars to avoid bloating the system prompt
        if len(existing) > 500:
            existing = existing[-500:]
        mem_mgr.set_meta("user_profile", existing.strip())
        return f"Profile updated: {note.strip()[:100]}"
    except Exception as e:
        return f"Error updating profile: {e}"



def recall_conversation(query: str, limit: int = 5) -> str:
    """Search past conversation history via FTS5 full-text search.
    Use when the user references earlier topics, past decisions, or needs context."""
    if not HAS_MEMORY or not mem_mgr:
        return "Memory system not available."
    # Rate limit: max 3 calls per turn
    if not hasattr(session, 'recall_count'):
        session.recall_count = 0
    if session.recall_count >= 3:
        return "Recall limit reached (3 per turn)."
    session.recall_count += 1
    try:
        limit = min(max(1, limit), 20)
        results = mem_mgr.search_with_snippet(query, limit=limit, snippet_chars=150)
        if not results:
            return "No matching memories found."
        # Build a summary of what was actually discussed (filter noise)
        user_msgs = [r for r in results if r["role"] == "user"]
        real_topics = []
        noise_patterns = ["之前我们聊过什么", "之前聊过什么", "记忆", "你记得", "你还记得"]
        for r in user_msgs:
            text = r["content"][:80].replace("\n", " ")
            if text and not any(n in text for n in noise_patterns):
                if text not in real_topics:
                    real_topics.append(text)
        lines = [f"[Memory search: '{query}' — {len(results)} results]"]
        if real_topics:
            lines.append(f"These topics were discussed in past sessions: {'; '.join(real_topics[:5])}")
            lines.append("Answer the user's question based on the above. Do NOT say 'no history' if topics exist above.")
            lines.append("---")
        else:
            lines.append("No substantive past topics found in the results below.")
        for r in results:
            ts = r["timestamp"][:16] if r["timestamp"] else "--"
            role_label = "User" if r["role"] == "user" else "Assistant"
            snippet = r.get("snippet", r["content"][:300])
            lines.append(f"[{ts}] {role_label}: {snippet}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching memory: {e}"



TOOLS: List[Dict[str, Any]] = [
    # ---- 核心工具 ----
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Run a shell command and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "working_dir": {"type": "string", "description": "工作目录，默认为当前目录"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file (auto-detect encoding)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create/overwrite file. Python/script files go to output/ dir; text/data files also go to output/. Temp/test scratch files use temp/ prefix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path. Relative paths go to output/ folder. Use output/script.py for code."},
                    "content": {"type": "string", "description": "要写入的内容"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and subdirectories",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录绝对路径，默认为当前目录"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search files by glob pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
                    "directory": {"type": "string", "description": "搜索起始目录，默认为当前目录"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_content",
            "description": "Search text in files",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索文本或正则"},
                    "directory": {"type": "string", "description": "搜索目录，默认为当前目录"},
                    "file_filter": {"type": "string", "description": "文件名过滤，如 *.py"}
                },
                "required": ["pattern"]
            }
        }
    },
    # ---- 办公工具 (F6, F7) ----
    {
        "type": "function",
        "function": {
            "name": "read_excel",
            "description": "Read Excel file, optional sheet name",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel 文件绝对路径"},
                    "sheet_name": {"type": "string", "description": "工作表名称，默认第一个"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_excel",
            "description": "Write Excel file from JSON data",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Excel 文件绝对路径"},
                    "data": {"type": "string", "description": "JSON 格式数据"},
                    "sheet_name": {"type": "string", "description": "工作表名称，默认 Sheet1"}
                },
                "required": ["path", "data"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_word",
            "description": "Extract text from Word document",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Word 文件绝对路径"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_word",
            "description": "Create Word document",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Word 文件绝对路径"},
                    "content": {"type": "string", "description": "文档纯文本内容"},
                    "title": {"type": "string", "description": "文档标题（可选）"}
                },
                "required": ["path", "content"]
            }
        }
    },
    # ---- 截图 & OCR (F8, F9) ----
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Take screenshot (fullscreen or by window)",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_title": {"type": "string", "description": "窗口标题关键字，为空则全屏"},
                    "save_path": {"type": "string", "description": "保存路径，默认 temp/screenshot.png"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ocr_image",
            "description": "OCR image to extract Chinese/English text",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "图片文件绝对路径"}
                },
                "required": ["path"]
            }
        }
    },
    # ---- 网络 & 位置 ----
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch raw web page content",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "Extract readable text from web page",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Query weather by city (via wttr.in); call get_location first",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名（中文或英文），如 北京/Shanghai"}
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": "Get current location via Windows Location API (GPS/WiFi). Use this to find the user's city — do NOT try execute_command or web_fetch for location. Call this first before get_weather.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Web search; use topic=news, days=3 for news",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "topic": {"type": "string", "description": "news 或 general，默认 general"},
                    "days": {"type": "integer", "description": "只搜最近N天，查新闻时建议3-7"}
                },
                "required": ["query"]
            }
        }
    },
    # ---- F25: 技能系统 ----
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load a skill script from skills/",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能文件名（不含 .py）"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": "Create a new skill script",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能文件名（不含 .py）"},
                    "code": {"type": "string", "description": "完整 Python 代码"}
                },
                "required": ["name", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_skill",
            "description": "Edit a skill script",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能文件名（不含 .py）"},
                    "code": {"type": "string", "description": "新的完整 Python 代码"}
                },
                "required": ["name", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List all skill scripts (.py and .md)",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_md_skill",
            "description": "Load a .md behavioral skill (SKILL.md format) that guides your thinking and interaction protocol",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能文件名（不含 .md）"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_md_skills",
            "description": "List all available .md behavioral skills with their triggers",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # ---- F26: 定时任务 ----
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add scheduled task (interval or cron)",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称"},
                    "mode": {"type": "string", "description": "interval 或 cron"},
                    "schedule": {"type": "string", "description": "interval 时为秒数，cron 时为 '分 时 日 月 周'"},
                    "action": {"type": "string", "description": "execute_command / web_search / ai_review"},
                    "params": {"type": "string", "description": "JSON 格式的参数"}
                },
                "required": ["name", "mode", "schedule", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List all scheduled tasks",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_task",
            "description": "Remove a scheduled task by name",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称"}
                },
                "required": ["name"]
            }
        }
    },
    # ---- F27: GUI 自动化（需二次确认） ----
    {
        "type": "function",
        "function": {
            "name": "gui_click",
            "description": "Click at screen coords (needs GUI auto)",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X 坐标"},
                    "y": {"type": "integer", "description": "Y 坐标"},
                    "button": {"type": "string", "description": "left / right / middle，默认 left"},
                    "clicks": {"type": "integer", "description": "点击次数，默认 1"}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "gui_type",
            "description": "Type text at focus (needs GUI auto)",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文本"},
                    "interval": {"type": "number", "description": "每个字符间隔秒数，默认 0.01"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "gui_move",
            "description": "Move mouse to screen coords",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X 坐标"},
                    "y": {"type": "integer", "description": "Y 坐标"},
                    "duration": {"type": "number", "description": "移动耗时秒数，默认 0.5"}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "gui_hotkey",
            "description": "Send keyboard shortcut / hotkey. Use for Win+S, Ctrl+C, Alt+Tab etc. Do NOT use gui_type for shortcuts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"},
                             "description": "Key names in order. win=Windows key. e.g. ['win','s'] for Win+S, ['ctrl','c'] for Ctrl+C"}
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "gui_press",
            "description": "Press a single key: enter, tab, escape, backspace, delete, space, etc. For combos use gui_hotkey. Works on UWP apps (WeChat, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key name: enter, tab, escape, backspace, delete, space, up, down, left, right"}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "window_focus",
            "description": "Find a window by title (partial match) and bring it to foreground. Use BEFORE typing/clicking into an app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Part of the window title. e.g. '微信' for WeChat, '记事本' for Notepad"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_on_screen",
            "description": "Screenshot + OCR → find text/button positions. Returns center coords and bounds. Use instead of execute_python pixel scanning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Text to find on screen. e.g. '发送', '搜索', '周桓'. Returns coordinates for clicking."}
                },
                "required": ["description"]
            }
        }
    },
    # ---- F28: 浏览器自动化 ----
    {
        "type": "function",
        "function": {
            "name": "browser_open",
            "description": "Open browser to URL (needs browser auto)",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要访问的 URL"},
                    "headless": {"type": "boolean", "description": "是否无头模式，默认 false"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click element by CSS selector",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS 选择器"}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into input field",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS 选择器"},
                    "text": {"type": "string", "description": "要输入的文本"}
                },
                "required": ["selector", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Screenshot browser page",
            "parameters": {
                "type": "object",
                "properties": {
                    "output_path": {"type": "string", "description": "保存路径，默认 temp/browser_screenshot.png"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Close browser, clean temp profile",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # ---- System Info (C11) ----
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get system hardware and runtime info",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {"type": "function", "function": {"name": "git_status", "description": "Git status", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_diff", "description": "Git diff", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}, "staged": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_log", "description": "Git log", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}, "max_count": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_blame", "description": "Git blame", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}, "file": {"type": "string"}}, "required": ["file"]}}},
    {"type": "function", "function": {"name": "go_to_definition", "description": "Find symbol definition", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "line": {"type": "integer"}, "column": {"type": "integer"}, "symbol": {"type": "string"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "find_references", "description": "Find symbol references", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "directory": {"type": "string"}, "file_filter": {"type": "string"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "analyze_image", "description": "Analyze image content", "parameters": {"type": "object", "properties": {"image_path": {"type": "string"}, "question": {"type": "string"}}, "required": ["image_path"]}}},
    {"type": "function", "function": {"name": "capture_camera", "description": "Capture camera frame and analyze", "parameters": {"type": "object", "properties": {"camera_index": {"type": "integer"}, "question": {"type": "string"}}, "required": []}}},
    # ---- Python REPL ----
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code in a persistent REPL session. Variables persist across calls. Use for calculations, data analysis, or testing logic. Call with '__reset__' to clear session, '__info__' to check status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Max execution time in seconds, default 30"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_conversation",
            "description": "Search past conversation history. Use when the user asks about earlier topics, past decisions, or needs context from previous sessions. Returns relevant conversation snippets with timestamps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords or question"},
                    "limit": {"type": "integer", "description": "Max results, default 5 (1-20)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_profile",
            "description": "Add a note to the evolving user profile. Use when you learn about the user's preferences, coding style, projects, tools, language preference, or answer format preference. The profile persists across sessions and is injected into the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "What you learned about the user, e.g. 'prefers concise answers', 'works on a Python web project', 'uses VS Code', 'wants Chinese replies'"}
                },
                "required": ["note"]
            }
        }
    },
]

TOOL_MAP: Dict[str, Any] = {
    "execute_command": execute_command, "read_file": read_file,
    "write_file": write_file, "list_files": list_files,
    "search_files": search_files, "search_content": search_content,
    "read_excel": read_excel, "write_excel": write_excel,
    "read_word": read_word, "write_word": write_word,
    "take_screenshot": take_screenshot, "ocr_image": ocr_image,
    "web_fetch": web_fetch, "read_webpage": read_webpage,
    "get_weather": get_weather, "get_location": get_location,
    "web_search": web_search,
    "git_status": git_status, "git_diff": git_diff,
    "git_log": git_log, "git_blame": git_blame,
    "go_to_definition": go_to_definition, "find_references": find_references,
    "analyze_image": analyze_image, "analyse_image": analyze_image, "capture_camera": capture_camera,
    "load_skill": load_skill, "create_skill": create_skill,
    "edit_skill": edit_skill, "list_skills": list_skills,
    "load_md_skill": load_md_skill, "list_md_skills": list_md_skills,
    "add_task": add_task, "list_tasks": list_tasks,
    "remove_task": remove_task,
    "gui_click": gui_click, "gui_type": gui_type, "gui_move": gui_move,
    "gui_hotkey": gui_hotkey, "gui_press": gui_press,
    "window_focus": window_focus, "find_on_screen": find_on_screen,
    "browser_open": browser_open, "browser_click": browser_click,
    "browser_type": browser_type, "browser_screenshot": browser_screenshot,
    "browser_close": browser_close,
    "get_system_info": get_system_info,
    "speak_text": speak_text,
    "execute_python": execute_python,
    "recall_conversation": recall_conversation,
    "update_profile": update_profile,
}

def run_tool(name, args):
    func = TOOL_MAP.get(name)
    if func is None:
        return f"Error: unknown tool - {name}"
    sig = inspect.signature(func)
    valid = {k: v for k, v in args.items() if k in sig.parameters}
    return func(**valid)


def get_user_input():
    console.print()
    console.print(f"[bold cyan]你[/bold cyan] [dim]>[/dim] ", end="")

    if sys.platform == "win32":
        return _get_user_input_win32()
    else:
        return _get_user_input_unix()


def _get_user_input_win32():
    """Windows: 用 getwch() 逐字符读取，可靠检测多行粘贴"""
    import msvcrt

    # 清空控制台缓冲区中的残留字符（避免上次操作遗留的 \n 等）
    while msvcrt.kbhit():
        try:
            msvcrt.getwch()
        except Exception:
            break

    chars = []
    while True:
        try:
            ch = msvcrt.getwch()
        except (EOFError, KeyboardInterrupt):
            return None

        if ch == '\r' or ch == '\n':
            # Windows 回车产生 \r\n，消费掉紧随的 \n 防止残留
            if ch == '\r' and msvcrt.kbhit():
                try:
                    next_ch = msvcrt.getwch()
                    if next_ch != '\n':
                        # 不是 \n，放回去（用 ungetwch 不可用，忽略此罕见情况）
                        pass
                except Exception:
                    pass
            console.print()
            break
        elif ch == '\x08':  # Backspace
            if chars:
                deleted = chars.pop()
                # Wide chars (Chinese etc) take 2 columns → double erase
                w = unicodedata.east_asian_width(deleted)
                if w in ('W', 'F'):
                    sys.stdout.write('\b \b\b \b')
                else:
                    sys.stdout.write('\b \b')
                sys.stdout.flush()
        elif ch == '\x03':  # Ctrl+C — 优雅退出
            console.print("^C")
            return None
        elif ch == '\x1a':  # Ctrl+Z
            return None
        elif ch == '\xe0' or ch == '\x00':
            # 扩展键前缀（方向键等），跳过
            try:
                msvcrt.getwch()
            except Exception:
                pass
        elif ch == '\t':
            # Tab -> 4 空格
            chars.append(' ' * 4)
            sys.stdout.write(' ' * 4)
            sys.stdout.flush()
        elif ch >= ' ':
            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()

    line = ''.join(chars)

    # 多行粘贴检测：getwch 绕过 Python stdin 缓冲，kbhit 可靠
    try:
        import time as _time
        _time.sleep(0.05)
        if msvcrt.kbhit():
            extra_chars = []
            while msvcrt.kbhit():
                try:
                    extra_chars.append(msvcrt.getwch())
                except Exception:
                    break
            extra_text = ''.join(extra_chars)
            if extra_text.strip():
                extra_text = extra_text.replace('\r\n', '\n').replace('\r', '\n')
                extra_lines = [l for l in extra_text.split('\n') if l.strip()]
                if extra_lines:
                    get_user_input._paste_count += 1
                    c = get_user_input._paste_count
                    n = len(extra_lines)
                    full_text = line + '\n' + '\n'.join(extra_lines)
                    # 预览前 120 字符
                    preview = full_text if len(full_text) <= 120 else full_text[:120] + "..."
                    console.print(f"  [Pasted text #{c} +{n} lines]", style="dim")
                    console.print(f"  {preview}", style="dim")
                    console.print("  [[dim]Enter=发送  e=编辑  q=取消[/dim]] ", end="")
                    try:
                        choice = msvcrt.getwch()
                    except Exception:
                        choice = '\r'
                    console.print()
                    if choice.lower() == 'q':
                        console.print("  [dim]已取消[/dim]")
                        return ""
                    if choice.lower() == 'e':
                        console.print("  [dim]正在打开记事本编辑...[/dim]")
                        import tempfile, subprocess
                        tmp = tempfile.NamedTemporaryFile(
                            mode='w', suffix='.txt', delete=False, encoding='utf-8')
                        tmp.write(full_text)
                        tmp_path = tmp.name
                        tmp.close()
                        subprocess.run(['notepad', tmp_path])
                        try:
                            with open(tmp_path, 'r', encoding='utf-8') as f:
                                edited = f.read().strip()
                        except Exception:
                            edited = ""
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass
                        if not edited:
                            console.print("  [dim]已取消[/dim]")
                            return ""
                        console.print(f"  [Pasted text #{c} +{n} lines]", style="dim")
                        return edited
                    # Enter (default) or any other key -> send as-is
                    return full_text
    except Exception:
        pass

    if not line.strip():
        return ""

    cmd = line.strip()
    if cmd.startswith("/"):
        return cmd

    if line.rstrip().endswith("\\\\"):
        lines = [line.rstrip()[:-2]]
        while True:
            try:
                console.print("   ", end="")
                next_line = input()
                if next_line.rstrip().endswith("\\\\"):
                    lines.append(next_line.rstrip()[:-2])
                else:
                    lines.append(next_line)
                    break
            except (EOFError, KeyboardInterrupt):
                break
        return "\n".join(lines)

    return line


def _get_user_input_unix():
    """Unix: input() + select 检测多行粘贴"""
    try:
        line = input()
    except (EOFError, KeyboardInterrupt):
        return None

    if not line.strip():
        return ""

    cmd = line.strip()
    if cmd.startswith("/"):
        return cmd

    try:
        import select, time as _time
        _time.sleep(0.05)
        if select.select([sys.stdin], [], [], 0.1)[0]:
            remaining = sys.stdin.read()
            if remaining.strip():
                get_user_input._paste_count += 1
                c = get_user_input._paste_count
                n = remaining.count("\n") + 1
                full_text = line + remaining.rstrip()
                console.print(f"  [Pasted text #{c} +{n} lines]", style="dim")
                return full_text
    except Exception:
        pass

    if line.rstrip().endswith("\\\\"):
        lines = [line.rstrip()[:-2]]
        while True:
            try:
                console.print("   ", end="")
                next_line = input()
                if next_line.rstrip().endswith("\\\\"):
                    lines.append(next_line.rstrip()[:-2])
                else:
                    lines.append(next_line)
                    break
            except (EOFError, KeyboardInterrupt):
                break
        return "\n".join(lines)

    return line


get_user_input._paste_count = 0


def main():
    history_path = SAVE_DIR / "chat_history.json"
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list) and len(loaded) > 0:
                if loaded[0].get("role") != "system":
                    raise ValueError("Bad history: first msg not system")
                expected = build_system_prompt()
                if loaded[0].get("content") != expected:
                    raise ValueError("System prompt mismatch")
                session.messages = sanitize_messages(loaded)
                console.print(f"[green]Loaded history ({len(session.messages)} msgs)[/green]")
            else:
                session.messages = []
        except Exception as e:
            console.print(f"[yellow]History load failed: {e}[/yellow]")
            session.messages = []
    else:
        session.messages = []

    if not session.messages:
        session.messages = [{"role": "system", "content": build_system_prompt()}]
        # Inject rolling summary from previous sessions
        if HAS_MEMORY and mem_mgr:
            try:
                summary = mem_mgr.get_meta("rolling_summary")
                time_range = mem_mgr.get_meta("rolling_summary_range") or ""
                if summary:
                    ctx = f"[Previous conversation context ({time_range})]: {summary}"
                    session.messages.append({"role": "user", "content": ctx})
                    session.messages.append({"role": "assistant", "content": "Got it, I have the context."})
            except Exception:
                pass

    mcp_count = init_mcp_tools()
    last_request_time = 0
    show_welcome()
    if mcp_count:
        console.print(f"[dim]MCP: {len(mcp_count)} external tools loaded[/dim]")

    while True:
        print_gap()
        ttl_warning = ""
        if last_request_time > 0 and (time.time() - last_request_time) > 300:
            ttl_warning = " [red](cache may be stale)[/red]"

        user_input = get_user_input()
        if user_input is None:
            auto_save(); cleanup_temp_files()
            _scheduler_shutdown.set()
            console.print("[dim]Goodbye[/dim]"); break
        if not user_input:
            continue

        is_voice = False
        if user_input.startswith("/"):
            cmd = user_input.lower().strip()
            if cmd == "/help":
                show_help()
            elif cmd == "/clear":
                session.messages = [{"role": "system", "content": build_system_prompt()}]
                session.turns = 0; session.tool_calls = 0
                console.print("[green]Cleared (DB preserved)[/green]")
            elif cmd == "/clear --all":
                session.messages = [{"role": "system", "content": build_system_prompt()}]
                session.turns = 0; session.tool_calls = 0
                if HAS_MEMORY and mem_mgr:
                    try:
                        n = mem_mgr.clear_all()
                        console.print(f"[green]Cleared all ({n} messages + meta)[/green]")
                    except Exception:
                        console.print("[yellow]Cleared window, DB clear failed[/yellow]")
                else:
                    console.print("[green]Cleared[/green]")
            elif cmd == "/stats":
                show_stats()
            elif cmd == "/save":
                p = save_conversation(export=True); auto_save()
                if p: console.print(f"[dim]Saved: {p}[/dim]")
            elif cmd == "/cache":
                show_cache()
            elif cmd == "/think":
                if session.last_thinking:
                    console.print(); console.print("[dim]Last thinking:[/dim]")
                    console.print(Markdown(session.last_thinking.strip()))
                else: console.print("[dim]No thinking recorded[/dim]")
            elif cmd == "/skills":
                console.print(); console.print("[bold]Skills[/bold]")
                if _loaded_skills:
                    console.print("[dim]已加载工具技能 (.py):[/dim]")
                    for fn, sk in _loaded_skills.items():
                        console.print(f"  {fn} (from {sk}.py)")
                else: console.print("[dim]已加载工具技能 (.py): (none)[/dim]")
                if _autoload_skills_cache:
                    console.print("[dim]已激活行为技能 (.md):[/dim]")
                    for sk in sorted(_autoload_skills_cache):
                        cached = _md_skill_cache.get(sk, {})
                        desc = cached.get("meta", {}).get("description", "")
                        label = f"  {sk}"
                        if desc:
                            label += f" — {desc}"
                        console.print(label)
                else: console.print("[dim]已激活行为技能 (.md): (none)[/dim]")
                console.print(); console.print("[bold]Available:[/bold]")
                console.print(list_skills())
            elif cmd == "/tasks":
                console.print(); console.print("[bold]Tasks[/bold]")
                console.print(list_tasks())
            elif cmd == "/memories":
                console.print(); console.print("[bold]Memory System[/bold]")
                if HAS_MEMORY and mem_mgr:
                    try:
                        count = mem_mgr.get_memory_count()
                        console.print(f"[dim]Total messages: {count}[/dim]")
                        summary = mem_mgr.get_meta("rolling_summary")
                        tr = mem_mgr.get_meta("rolling_summary_range") or ""
                        if summary:
                            console.print(f"[dim]Summary ({tr}): {summary[:200]}[/dim]")
                        recent = mem_mgr.get_recent_turns(limit=10)
                        if recent:
                            console.print("[dim]Recent:[/dim]")
                            for r in recent:
                                ts = r["timestamp"][:16] if r["timestamp"] else ""
                                role = "U" if r["role"] == "user" else "A"
                                snippet = r["content"][:100].replace("\n", " ")
                                console.print(f"  [{ts}] {role}: {snippet}")
                        else:
                            console.print("[dim](no messages yet)[/dim]")
                    except Exception as e:
                        console.print(f"[red]Error: {e}[/red]")
                else:
                    console.print("[yellow]Memory system not enabled[/yellow]")
            elif cmd.startswith("/profile"):
                handle_profile_cmd(user_input)
            elif cmd.startswith("/config"):
                handle_config_cmd(user_input)
            elif cmd.startswith("/search "):
                kw = cmd[8:].strip().lower()
                found = [m.get('content','') for m in session.messages if m.get('content') and kw in m.get('content','').lower()]
                if found: console.print(f"[green]{len(found)} matches:[/green]\n" + "\n---\n".join([c[:200] for c in found[:5]]))
                else: console.print("[yellow]No matches[/yellow]")
            elif cmd == "/tts":
                console.print("[cyan]Testing TTS...[/cyan]")
                speak_text("TTS test. Hello world.")
            elif cmd == "/voice":
                if not ENABLE_VOICE: console.print("[yellow]Voice disabled[/yellow]")
                elif not HAS_SPEECH_RECOGNITION: console.print("[red]No speech module[/red]")
                else:
                    console.print(f"[cyan]Listening... ({SPEECH_BACKEND})[/cyan]")
                    r = voice_input()
                    if r and r.strip():
                        console.print(f"\n[green]Recognized: {r}[/green]")
                        user_input = r.strip(); is_voice = True
                    else: console.print("[yellow]Nothing recognized[/yellow]")
            else: console.print(f"[yellow]Unknown: {cmd}[/yellow]")
            if not is_voice: continue

        # ---- Auto-trigger SKILL.md matching ----
        for md_file in sorted(SKILLS_DIR.glob("*.md")):
            name = md_file.stem
            if name in _autoload_skills_cache:
                continue
            parsed = _md_skill_cache.get(name) or _parse_skill_md(md_file)
            if not parsed:
                continue
            _md_skill_cache[name] = parsed
            triggers = parsed["meta"].get("triggers", [])
            for trigger in triggers:
                hit = False
                if any(c in trigger for c in ('.*', '^', '$', '\\d', '\\w', '|', '[', ']', '(', ')')):
                    try:
                        if re.search(trigger, user_input, re.IGNORECASE):
                            hit = True
                    except re.error:
                        pass
                else:
                    if trigger.lower() in user_input.lower():
                        hit = True
                if hit:
                    console.print(f"[dim]触发技能: {name}[/dim]")
                    load_md_skill(name)
                    break

        if user_input.strip().lower() in ("exit", "quit"):
            auto_save(); cleanup_temp_files()
            _scheduler_shutdown.set()
            console.print("[dim]Goodbye[/dim]"); break

        # Auto-detect image paths
        img_pat = re.compile(r'([a-zA-Z]:\\[^"\'<>|?*]+\.(?:jpg|jpeg|png|gif|webp|bmp))', re.IGNORECASE)
        imgs = img_pat.findall(user_input)
        if imgs:
            if IS_MULTIMODAL:
                # Embed image directly for multimodal models
                import base64 as _b64
                p = Path(imgs[0])
                if p.exists() and p.stat().st_size < 10 * 1024 * 1024:
                    with open(p, "rb") as f:
                        img_data = _b64.b64encode(f.read()).decode('utf-8')
                    mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png',
                            'gif':'image/gif','webp':'image/webp','bmp':'image/bmp'}
                    mime_type = mime.get(p.suffix.lower().replace('.',''), 'image/jpeg')
                    prompt = user_input.replace(imgs[0], '').strip() or "Please analyze this image:"
                    session.messages.append({"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_data}"}}
                    ]})
                    console.print("[dim]Image embedded directly (multimodal mode)[/dim]")
                else:
                    session.messages.append({"role": "user", "content": user_input})
            elif not any(kw in user_input.lower() for kw in ['analyze','describe','look']):
                user_input = f"Please analyze this image: {imgs[0]}"
                console.print("[dim]Image path detected, auto-prompting...[/dim]")
                session.messages.append({"role": "user", "content": user_input})
            else:
                session.messages.append({"role": "user", "content": user_input})
        else:
            session.messages.append({"role": "user", "content": user_input})
        session.turns += 1
        if not hasattr(session, 'recall_count'):
            session.recall_count = 0
        session.recall_count = 0
        generated_files = set()
        reasoning = ""
        answer = ""

        while True:
            session.messages = sanitize_messages(session.messages)
            session.messages = smart_trim_messages(session.messages, llm_client=client, llm_model=MODEL)
            try:
                stream = call_model(session.messages)
            except openai.NotFoundError as e:
                console.print(f"[bold red]404: Model '{MODEL}' not found[/bold red]")
                logging.error(f"Model: {e}"); session.messages.pop(); session.turns -= 1; break
            except openai.AuthenticationError as e:
                console.print(f"[bold red]401: Invalid API key[/bold red]")
                logging.error(f"Auth: {e}"); session.messages.pop(); session.turns -= 1; break
            except openai.BadRequestError as e:
                console.print(f"[bold red]400: {e}[/bold red]")
                logging.error(f"BadReq: {e}"); session.messages.pop(); session.turns -= 1; break
            except KeyboardInterrupt:
                console.print("\n[yellow]⏎ Interrupted by user[/yellow]")
                session.messages.pop(); session.turns -= 1; break
            except Exception as e:
                console.print(f"[bold red]API Error: {e}[/bold red]")
                logging.error(f"API: {e}"); session.messages.pop(); session.turns -= 1; break

            try:
                reasoning, answer, tool_calls_idx, usage = process_stream(stream)
            except KeyboardInterrupt:
                console.print("\n[yellow]⏎ Stream interrupted[/yellow]")
                session.messages.pop(); session.turns -= 1; break

            if usage:
                session.add_usage(usage); show_usage(usage)

            if tool_calls_idx:
                tc_list, tr_list = execute_tool_calls(tool_calls_idx)
                for tc in tc_list:
                    if tc['function']['name'] in ('write_file','write_excel','write_word','take_screenshot'):
                        try:
                            generated_files.add(str(Path(json.loads(tc['function']['arguments'])['path']).resolve()))
                        except: pass
                session.messages.append({
                    "role":"assistant","content":answer or None,
                    "reasoning_content":reasoning,"tool_calls":tc_list})

                # Multimodal: detect __IMAGE__: prefix in tool results and inject image
                injected = False
                for i, tr in enumerate(tr_list):
                    content = tr.get("content", "")
                    if isinstance(content, str) and content.startswith("__IMAGE__:"):
                        data_uri = content[len("__IMAGE__:"):]
                        session.messages.extend([
                            {"role": "user", "content": [
                                {"type": "text", "text": "Here is the image:"},
                                {"type": "image_url", "image_url": {"url": data_uri}}
                            ]},
                            {"role": "assistant", "content": "Image received, analyzing..."}
                        ])
                        tr_list[i] = {"role": "tool", "tool_call_id": tr["tool_call_id"],
                                       "content": "[Image embedded directly for multimodal model]"}
                        injected = True
                        console.print("[dim]  [multimodal] Image injected into conversation[/dim]")
                if injected:
                    session.messages.extend(tr_list)
                    continue
                else:
                    session.messages.extend(tr_list)
                    continue

            if answer:
                print_soft_gap()
                # Auto TTS
                if HAS_TTS and ENABLE_TTS and answer.strip():
                    try:
                        clean = answer
                        clean = re.sub(r'```[\s\S]*?```','',clean)
                        clean = re.sub(r'!\[.*?\]\(.*?\)',r'\1',clean)
                        clean = re.sub(r'\[(.+?)\]\(.+?\)',r'\1',clean)
                        clean = re.sub(r'\*\*(.+?)\*\*',r'\1',clean)
                        clean = re.sub(r'`(.+?)`',r'\1',clean)
                        clean = re.sub(r'^#{1,6}\s+','',clean,flags=re.MULTILINE)
                        clean = re.sub(r'^\s*[-*+]\s+','',clean,flags=re.MULTILINE)
                        clean = re.sub(r'\n{3,}','\n\n',clean); clean = clean.strip()
                        if clean: speak_text(clean)
                    except: pass

            session.messages.append({
                "role":"assistant","content":answer,"reasoning_content":reasoning})
            break

        cleaned = cleanup_temp_files(generated_files)
        if cleaned: console.print(f"[dim]  {cleaned}[/dim]")
        auto_save(); last_request_time = time.time()

        # Save turn to memory
        if HAS_MEMORY and mem_mgr and answer:
            # Find the last user message
            last_user = ""
            for m in reversed(session.messages[:-1]):
                if m.get("role") == "user":
                    last_user = m.get("content", "")
                    break
            if last_user:
                try:
                    sid = datetime.now().strftime("%Y%m%d")
                    turn = session.turns
                    mem_mgr.save_message(sid, turn, "user", str(last_user)[:10000])
                    mem_mgr.save_message(sid, turn, "assistant", str(answer)[:10000])
                except Exception:
                    pass

        tokens = session.total_input_tokens + session.total_output_tokens
        # Fallback: if API didn't report usage, estimate from conversation size
        if tokens == 0 and session.turns > 0:
            tokens = sum(_msg_tokens(m) for m in session.messages)
            est_mark = "~"
        else:
            est_mark = ""
        # Cache hit rate: cached / total input
        if session.total_input_tokens > 0 and session.total_cached_tokens > 0:
            hit_rate = session.total_cached_tokens / session.total_input_tokens * 100
            c_str = f" | 缓存命中 {session.total_cached_tokens:,} ({hit_rate:.0f}%)"
        elif session.total_cached_tokens > 0:
            c_str = f" | 缓存命中 {session.total_cached_tokens:,}"
        else:
            c_str = ""
        r_str = f" | 思考 {session.total_reasoning_tokens:,}" if session.total_reasoning_tokens > 0 else ""
        bal = get_api_balance()
        console.print(
            f"[dim]Turn {session.turns} | Tools {session.tool_calls} | "
            f"{est_mark}{tokens:,} tokens{c_str}{r_str} | Bal {bal} | {session.elapsed}{ttl_warning}[/dim]"
        )

if __name__ == "__main__":
    main()
