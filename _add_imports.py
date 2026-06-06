"""Add required imports to each extracted module."""
import os, sys

OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ultimate_agent')

MODULE_IMPORTS = {
    'utils.py': '\n'.join([
        'import os, sys, re, json, tempfile, shutil, time',
        'from pathlib import Path',
        'from typing import Any, Dict, Tuple',
    ]),
    'security.py': '\n'.join([
        'import re, ipaddress, urllib.parse, hashlib, logging',
        'import ast as _ast',
        'from pathlib import Path',
        'from typing import Optional',
    ]),
    'tools_core.py': '\n'.join([
        'import os, sys, re, subprocess, shlex, platform, getpass',
        'import glob as glob_mod',
        'from pathlib import Path',
        'from datetime import datetime',
        'import logging',
        'from ultimate_agent.config import (CONFIG, API_KEY, BASE_URL, MODEL,',
        '    CMD_TIMEOUT, SILENT_CMD, WORKING_DIR, SCRIPT_DIR, TERM_WIDTH, console)',
        'from ultimate_agent.utils import _detect_encoding, _validate_write_path, _estimate_tokens',
        'from ultimate_agent.security import _DANGEROUS_PATTERNS',
    ]),
    'tools_office.py': '\n'.join([
        'import os, sys, json, time, logging, threading',
        'from pathlib import Path',
        'from ultimate_agent.config import (CONFIG, TEMP_DIR, ensure_pkg, console)',
        'from ultimate_agent.utils import _validate_write_path',
    ]),
    'tools_web.py': '\n'.join([
        'import os, sys, json, re, subprocess, logging',
        'import urllib.request, urllib.error, urllib.parse',
        'import hashlib',
        'from pathlib import Path',
        'from typing import Optional, Dict, List, Tuple',
        'from ultimate_agent.config import (CONFIG, TAVILY_API_KEY, USER_CITY,',
        '    TERM_WIDTH, SCRIPT_DIR, search_cache, console)',
        'from ultimate_agent.security import _is_safe_url',
    ]),
    'tools_dev.py': '\n'.join([
        'import os, sys, re, base64, time, tempfile, subprocess',
        'from pathlib import Path',
        'from datetime import datetime',
        'import openai',
        'from openai import OpenAI',
        'from ultimate_agent.config import (CONFIG, MODEL, BASE_URL, API_KEY,',
        '    IS_MULTIMODAL, VISION_MODEL, VISION_BASE_URL, VISION_API_KEY,',
        '    WORKING_DIR, TEMP_DIR, HAS_OPENCV, HAS_PILLOW, client, console)',
    ]),
    'tools_skills.py': '\n'.join([
        'import os, json, re, threading, time',
        'import ast as _ast',
        'from pathlib import Path',
        'from typing import Optional, Dict',
        'from datetime import datetime',
        'from ultimate_agent.config import (CONFIG, SKILLS_DIR, LOGS_DIR, SCRIPT_DIR,',
        '    console)',
        'from ultimate_agent.security import (_SKILL_BLACKLIST, _SKILL_DANGEROUS_ATTRS,',
        '    _SKILL_SAFE_BUILTINS, _scan_skill_ast, _safe_exec_skill)',
        'from ultimate_agent.tools_core import execute_command',
        'from ultimate_agent.tools_web import web_search',
    ]),
    'tools_automation.py': '\n'.join([
        'import os, sys, subprocess, shutil, threading, time',
        'from pathlib import Path',
        'from typing import Optional, Dict',
        'from ultimate_agent.config import (CONFIG, ENABLE_GUI_AUTO,',
        '    ENABLE_BROWSER_AUTO, TEMP_DIR, ensure_pkg, console)',
        'from ultimate_agent.security import _is_safe_url',
    ]),
    'tts_mcp.py': '\n'.join([
        'import os, sys, json, asyncio, subprocess, threading, tempfile, time',
        'from pathlib import Path',
        'from datetime import datetime',
        'from ultimate_agent.config import (CONFIG, HAS_TTS, HAS_BERT_VITS2,',
        '    HAS_SPEECH_RECOGNITION, ENABLE_TTS, ENABLE_VOICE, SPEECH_BACKEND,',
        '    SCRIPT_DIR, WORKING_DIR, console)',
    ]),
    'session.py': '\n'.join([
        'import os, sys, json, re, time, logging, inspect',
        'from pathlib import Path',
        'from datetime import datetime',
        'from typing import Optional, Dict, Any, List',
        'from concurrent.futures import ThreadPoolExecutor, as_completed',
        'import threading',
        'import openai',
        'from openai import OpenAI',
        'import tenacity',
        'from rich.markdown import Markdown',
        'from rich.padding import Padding',
        'from rich.table import Table',
        'from ultimate_agent.config import (CONFIG, MODEL, BASE_URL, API_KEY,',
        '    IS_DEEPSEEK, IS_LOCAL, IS_MULTIMODAL, USE_SIMPLE_PROMPT,',
        '    ENABLE_THINK_MODE, REASONING_EFFORT, MAX_OUTPUT_TOKENS,',
        '    CONTEXT_MAX_TOKENS, KEEP_ROUNDS, PERSONA, HAS_MEMORY, HAS_TTS,',
        '    ENABLE_TTS, ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO, VISION_MODEL,',
        '    TERM_WIDTH, SAVE_DIR, WORKING_DIR, mem_mgr, client, console)',
        'from ultimate_agent.utils import _sanitize_ansi, _strip_html, _estimate_tokens',
        'from ultimate_agent.tools_core import get_system_info',
    ]),
    'main.py': '\n'.join([
        'import os, sys, json, re, time, unicodedata, inspect',
        'import base64',
        'from pathlib import Path',
        'from datetime import datetime',
        'from typing import Dict, Any',
        'from ultimate_agent.config import (CONFIG, SCRIPT_DIR, SAVE_DIR, TEMP_DIR,',
        '    SKILLS_DIR, WORKING_DIR, HAS_MEMORY, HAS_SPEECH_RECOGNITION,',
        '    ENABLE_VOICE, SPEECH_BACKEND, ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO,',
        '    IS_MULTIMODAL, MODEL, BASE_URL, API_KEY, TERM_WIDTH,',
        '    mem_mgr, console, client, mask_key, get_api_balance)',
        'from ultimate_agent.tools_core import *',
        'from ultimate_agent.tools_office import *',
        'from ultimate_agent.tools_web import *',
        'from ultimate_agent.tools_dev import *',
        'from ultimate_agent.tools_skills import *',
        'from ultimate_agent.tools_automation import *',
        'from ultimate_agent.tts_mcp import (speak_text, voice_input, init_mcp_tools,',
        '    init_speech_recognition)',
        'from ultimate_agent.session import *',
        'from ultimate_agent.utils import (_msg_tokens, _estimate_tokens,',
        '    cleanup_temp_files, resolve_tool_path)',
        '# Memory + REPL',
        'try:',
        '    from memory_manager import MemoryManager',
        'except ImportError:',
        '    MemoryManager = None',
        'try:',
        '    from python_repl import execute_python',
        '    HAS_PYTHON_REPL = True',
        'except ImportError:',
        '    HAS_PYTHON_REPL = False',
        '    def execute_python(code, timeout=30): return "REPL not available"',
    ]),
}

for mod_name, import_block in MODULE_IMPORTS.items():
    path = os.path.join(OUTDIR, mod_name)
    if not os.path.exists(path):
        print(f'SKIP {mod_name}: not found')
        continue
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    # Find end of module docstring
    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('"""') and i > 0:
            insert_at = i + 1
            break
        elif line.strip().startswith('"""'):
            for j in range(i + 1, len(lines)):
                if '"""' in lines[j]:
                    insert_at = j + 1
                    break
            break

    new_lines = lines[:insert_at] + ['', import_block, ''] + lines[insert_at:]
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    print(f'{mod_name}: imports added at line {insert_at}')

print('Done.')
