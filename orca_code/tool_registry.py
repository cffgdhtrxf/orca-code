"""orca_code.tool_registry — Centralized tool definitions and function mapping.

TOOLS: List of OpenAI-format tool definitions (JSON schemas).
TOOL_MAP: Dict mapping tool names to callable functions.
run_tool(): Permission-checked tool dispatch.

This module breaks the circular dependency between main.py and its consumers
(session.py, tools_skills.py, subagent.py, tts_mcp.py). All imports from this
module are direct — no lazy-load workarounds needed.

For tool functions defined in main.py itself (update_profile, recall_conversation),
lazy tuple markers are used to avoid import loops with main.py.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Dict, List, Optional

# ─── Direct imports from non-circular tool modules ───────────────────────────
from orca_code.tools_core import (
    execute_command, read_file, write_file, edit_file, apply_diff,
    list_files, search_files, search_content, get_system_info,
)
from orca_code.tools_office import (
    read_excel, write_excel, read_word, write_word, take_screenshot, ocr_image,
)
from orca_code.tools_web import (
    web_fetch, read_webpage, get_weather, get_location, web_search,
)
from orca_code.tools_dev import (
    git_status, git_diff, git_log, git_blame,
    go_to_definition, find_references, analyze_image, capture_camera,
)
from orca_code.tools_automation import (
    gui_click, gui_type, gui_move, gui_hotkey, gui_press,
    window_focus, find_on_screen,
    browser_open, browser_click, browser_type, browser_screenshot, browser_close,
)
from orca_code.tools_skills import (
    load_skill, create_skill, edit_skill, list_skills,
    load_md_skill, list_md_skills,
    add_task, list_tasks, remove_task,
)
from orca_code.tts_mcp import speak_text
from orca_code.subagent import agent_open, agent_eval, agent_close
from orca_code.lsp import lsp_diagnostics, lsp_references, lsp_definition

# ─── Optional: Python REPL ───────────────────────────────────────────────────
try:
    from _python_repl import execute_python
    HAS_PYTHON_REPL = True
except ImportError:
    HAS_PYTHON_REPL = False
    def execute_python(code, timeout=30): return "REPL not available"


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS — OpenAI-format tool definitions
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS: List[Dict[str, Any]] = [
    # ── Core tools ──
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
            "name": "edit_file",
            "description": "Precise string replacement in a file. Provide old_string (must be unique in file) and new_string. Like find-and-replace for one occurrence. Use for small targeted changes instead of rewriting the whole file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "The exact text to replace (must be unique in file)"},
                    "new_string": {"type": "string", "description": "The replacement text"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_diff",
            "description": "Apply a unified diff to a file. Use for batch changes from git diff output. Supports standard @@ -x,y +a,b @@ hunk format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file path"},
                    "diff_text": {"type": "string", "description": "Unified diff text to apply"}
                },
                "required": ["path", "diff_text"]
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
    # ── Office tools ──
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
    # ── Screenshot & OCR ──
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
    # ── Web & location ──
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
    # ── Skills system ──
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
    # ── Scheduled tasks ──
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
    # ── GUI automation ──
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
    # ── Browser automation ──
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
    # ── System info ──
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get system hardware and runtime info",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    # ── LSP ──
    {
        "type": "function",
        "function": {
            "name": "lsp_diagnostics",
            "description": "Get language server diagnostics (errors/warnings) for a file. Supports Python, TypeScript, Rust, Go. Requires LSP server installed (pylsp, ts-ls, rust-analyzer, gopls).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the source file"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_references",
            "description": "Find all references to a symbol at a position (Go to References).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path"},
                    "line": {"type": "integer", "description": "Line number (1-based)"},
                    "column": {"type": "integer", "description": "Column number (1-based, default 1)"}
                },
                "required": ["file_path", "line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "lsp_definition",
            "description": "Go to the definition of a symbol at a position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path"},
                    "line": {"type": "integer", "description": "Line number (1-based)"},
                    "column": {"type": "integer", "description": "Column number (1-based, default 1)"}
                },
                "required": ["file_path", "line"]
            }
        }
    },
    # ── Git ──
    {"type": "function", "function": {"name": "git_status", "description": "Git status", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_diff", "description": "Git diff", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}, "staged": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_log", "description": "Git log", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}, "max_count": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_blame", "description": "Git blame", "parameters": {"type": "object", "properties": {"repo_path": {"type": "string"}, "file": {"type": "string"}}, "required": ["file"]}}},
    {"type": "function", "function": {"name": "go_to_definition", "description": "Find symbol definition", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "line": {"type": "integer"}, "column": {"type": "integer"}, "symbol": {"type": "string"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "find_references", "description": "Find symbol references", "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}, "directory": {"type": "string"}, "file_filter": {"type": "string"}}, "required": ["symbol"]}}},
    {"type": "function", "function": {"name": "analyze_image", "description": "Analyze image content", "parameters": {"type": "object", "properties": {"image_path": {"type": "string"}, "question": {"type": "string"}}, "required": ["image_path"]}}},
    {"type": "function", "function": {"name": "capture_camera", "description": "Capture camera frame and analyze", "parameters": {"type": "object", "properties": {"camera_index": {"type": "integer"}, "question": {"type": "string"}}, "required": []}}},
    # ── Python REPL ──
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
    # ── Memory & profile ──
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
    # ── Sub-agents ──
    {
        "type": "function",
        "function": {
            "name": "agent_open",
            "description": "Launch a background sub-agent to investigate a task. Non-blocking — returns a handle immediately. Use for parallel research like searching multiple files simultaneously. Max 5 concurrent agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What the sub-agent should do. Be specific."},
                    "tools": {"type": "string", "description": "Comma-separated tool names. Default: read_file,search_content,list_files."},
                    "context": {"type": "string", "description": "Optional additional context"}
                },
                "required": ["task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_eval",
            "description": "Get the result of a previously launched sub-agent. Blocks until completion (up to 60s). Returns structured findings summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "Handle from agent_open (format: sub://XXXXX)."},
                    "timeout": {"type": "integer", "description": "Max seconds to wait. Default 60."}
                },
                "required": ["handle"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_close",
            "description": "Terminate a running sub-agent and clean up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "Handle from agent_open (format: sub://XXXXX)."}
                },
                "required": ["handle"]
            }
        }
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL_MAP — name → callable mapping
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_MAP: Dict[str, Any] = {
    # Core
    "execute_command": execute_command, "read_file": read_file,
    "write_file": write_file, "edit_file": edit_file, "apply_diff": apply_diff,
    "list_files": list_files,
    "search_files": search_files, "search_content": search_content,
    # Office
    "read_excel": read_excel, "write_excel": write_excel,
    "read_word": read_word, "write_word": write_word,
    "take_screenshot": take_screenshot, "ocr_image": ocr_image,
    # Web
    "web_fetch": web_fetch, "read_webpage": read_webpage,
    "get_weather": get_weather, "get_location": get_location,
    "web_search": web_search,
    # Dev
    "git_status": git_status, "git_diff": git_diff,
    "git_log": git_log, "git_blame": git_blame,
    "go_to_definition": go_to_definition, "find_references": find_references,
    "analyze_image": analyze_image, "analyse_image": analyze_image, "capture_camera": capture_camera,
    # Skills
    "load_skill": load_skill, "create_skill": create_skill,
    "edit_skill": edit_skill, "list_skills": list_skills,
    "load_md_skill": load_md_skill, "list_md_skills": list_md_skills,
    # Tasks
    "add_task": add_task, "list_tasks": list_tasks,
    "remove_task": remove_task,
    # GUI
    "gui_click": gui_click, "gui_type": gui_type, "gui_move": gui_move,
    "gui_hotkey": gui_hotkey, "gui_press": gui_press,
    "window_focus": window_focus, "find_on_screen": find_on_screen,
    # Browser
    "browser_open": browser_open, "browser_click": browser_click,
    "browser_type": browser_type, "browser_screenshot": browser_screenshot,
    "browser_close": browser_close,
    # System
    "get_system_info": get_system_info,
    # TTS
    "speak_text": speak_text,
    # REPL
    "execute_python": execute_python,
    # Sub-agents
    "agent_open": agent_open, "agent_eval": agent_eval, "agent_close": agent_close,
    # LSP
    "lsp_diagnostics": lsp_diagnostics,
    "lsp_references": lsp_references,
    "lsp_definition": lsp_definition,
}

# ── Lazy resolution markers (resolved on first call by run_tool) ─────────────
# These functions live in main.py which imports from tool_registry — avoid
# circular import by deferring resolution to call time.
_LAZY_TOOLS: Dict[str, tuple] = {
    "recall_conversation": ("orca_code.main", "recall_conversation"),
    "update_profile": ("orca_code.main", "update_profile"),
}


def _resolve(name: str):
    """Return the callable for a tool name, resolving lazy markers if needed."""
    if name in _LAZY_TOOLS and name not in TOOL_MAP:
        module_path, func_name = _LAZY_TOOLS[name]
        from importlib import import_module
        mod = import_module(module_path)
        TOOL_MAP[name] = getattr(mod, func_name)
    return TOOL_MAP.get(name)


def run_tool(name: str, args: dict) -> str:
    """Permission-checked tool dispatch. All tool calls flow through here."""
    func = _resolve(name)
    if func is None:
        return f"Error: unknown tool - {name}"

    # Permission check (Claude Code style)
    from orca_code.permissions import resolve_permission
    from orca_code.config import PERMISSION_MODE, PERMISSION_RULES
    if not resolve_permission(name, args, PERMISSION_MODE, PERMISSION_RULES):
        return f"Permission denied for '{name}'. Use /permissions to manage rules."

    sig = inspect.signature(func)
    valid = {k: v for k, v in args.items() if k in sig.parameters}
    result = func(**valid)

    # Constitution Article IV: verification markers
    from orca_code.constitution import verification_marker
    if isinstance(result, str):
        is_error = result.startswith("Error") or result.startswith("错误") or result.startswith("Permission denied")
        if is_error:
            result += verification_marker(False, "")
        elif name in ("write_file", "edit_file", "apply_diff"):
            result += verification_marker(True, f"tool={name}")
        elif name in ("execute_command", "execute_python"):
            result += verification_marker(True, f"tool={name}")

    return result
