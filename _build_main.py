"""Build clean main.py from legacy sections."""
with open('ultimate_agent_legacy.py', 'r', encoding='utf-8') as f:
    lines = f.read().split('\n')

sections = []
# update_profile: 3188-3206 (0-idx: 3187-3205)
sections.append('\n'.join(lines[3187:3206]))
# recall_conversation: 3207-3247 (0-idx: 3206-3247)
sections.append('\n'.join(lines[3206:3248]))
# TOOLS: 900-1444 (0-idx: 899-1443)
sections.append('\n'.join(lines[899:1444]))
# TOOL_MAP: 3249-3277 (0-idx: 3248-3276)
sections.append('\n'.join(lines[3248:3277]))
# run_tool: 3279-3286 (0-idx: 3278-3285)
sections.append('\n'.join(lines[3278:3286]))
# get_user_input + helpers: 3945-4152 (0-idx: 3944-4151)
sections.append('\n'.join(lines[3944:4152]))
# main: 4387-end (0-idx: 4386-4745)
sections.append('\n'.join(lines[4386:]))

body = '\n\n'.join(sections)

header = '''"""ultimate_agent.main — Tool registry, user input, main loop."""

import os, sys, json, re, time, unicodedata, inspect
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from ultimate_agent.config import (CONFIG, SCRIPT_DIR, SAVE_DIR, TEMP_DIR,
    SKILLS_DIR, WORKING_DIR, HAS_MEMORY, HAS_SPEECH_RECOGNITION,
    ENABLE_VOICE, SPEECH_BACKEND, ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO,
    IS_MULTIMODAL, MODEL, BASE_URL, API_KEY, TERM_WIDTH,
    mem_mgr, console, client, mask_key, get_api_balance)
from ultimate_agent.tools_core import *
from ultimate_agent.tools_office import *
from ultimate_agent.tools_web import *
from ultimate_agent.tools_dev import *
from ultimate_agent.tools_skills import *
from ultimate_agent.tools_automation import *
from ultimate_agent.tts_mcp import (speak_text, voice_input, init_mcp_tools,
    init_speech_recognition)
from ultimate_agent.session import *
from ultimate_agent.utils import (_msg_tokens, _estimate_tokens,
    cleanup_temp_files, resolve_tool_path)

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

'''

with open('ultimate_agent/main.py', 'w', encoding='utf-8') as f:
    f.write(header + body)

import py_compile
try:
    py_compile.compile('ultimate_agent/main.py', doraise=True)
    print('main.py: SYNTAX OK')
except py_compile.PyCompileError as e:
    print(f'SYNTAX ERROR: {e}')
