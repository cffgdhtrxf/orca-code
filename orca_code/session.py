"""orca_code.session — Session state, persistence, and re-export hub.

Implementation split across submodules:
  session_messages.py  — Message sanitization, compression, token estimation
  session_prompt.py    — System prompt construction
  session_ui.py        — Terminal UI rendering (Rich)
  session_stream.py    — LLM API calling, stream processing, tool execution

This module keeps the Session class, singleton, and persistence.
All public names are re-exported for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from orca_code.config import SAVE_DIR, mem_mgr
from orca_code.utils import _sanitize_for_save

# ── Re-export from submodules (backward compat) ────────────────────────────
from orca_code.session_messages import (
    _get_tools, _get_tool_map,
    sanitize_messages, _msg_tokens, _extract_text,
    _llm_compress_blocks, smart_trim_messages,
)
from orca_code.session_prompt import (
    build_system_prompt, _estimate_prefix_tokens,
)
from orca_code.session_ui import (
    print_gap, print_soft_gap,
    show_tool_call, show_tool_result, show_tool_done,
    show_usage, show_welcome, show_help, show_stats, show_cache,
)
from orca_code.session_stream import (
    call_model, process_stream, execute_tool_calls,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Session — conversation state
# ═══════════════════════════════════════════════════════════════════════════════

class Session:
    def __init__(self):
        self.turns: int = 0
        self.tool_calls: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cached_tokens: int = 0
        self.total_reasoning_tokens: int = 0
        self.start_time: float = __import__('time').time()
        self.messages: List[Dict] = []
        self.last_thinking: str = ''
        self.env_injected: bool = False

    def add_usage(self, usage) -> None:
        if not usage:
            return
        inp = getattr(usage, 'prompt_tokens', 0) or 0
        out = getattr(usage, 'completion_tokens', 0) or 0
        self.total_input_tokens += inp
        self.total_output_tokens += out
        # DeepSeek disk cache: prompt_cache_hit_tokens / prompt_cache_miss_tokens
        hit = getattr(usage, 'prompt_cache_hit_tokens', 0) or 0
        miss = getattr(usage, 'prompt_cache_miss_tokens', 0) or 0
        self.total_cached_tokens += hit
        # Legacy: prompt_tokens_details.cached_tokens (older API format)
        pd = getattr(usage, 'prompt_tokens_details', None)
        if pd and hasattr(pd, 'cached_tokens'):
            self.total_cached_tokens += (pd.cached_tokens or 0)
        cd = getattr(usage, 'completion_tokens_details', None)
        if cd and hasattr(cd, 'reasoning_tokens'):
            self.total_reasoning_tokens += (cd.reasoning_tokens or 0)

    @property
    def elapsed(self) -> str:
        import time
        t = time.time() - self.start_time
        if t < 60:
            return f'{t:.0f}秒'
        elif t < 3600:
            return f'{t / 60:.0f}分{t % 60:.0f}秒'
        else:
            return f'{t / 3600:.0f}时{(t % 3600) / 60:.0f}分'


session = Session()


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════════

def save_conversation(export=False):
    lines = []
    for msg in session.messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "system":
            continue
        elif role == "user":
            lines.append(f"## 你\n\n{content}\n")
        elif role == "assistant":
            lines.append(f"## 助手\n\n{content}\n")
            rc = msg.get("reasoning_content", "")
            if rc:
                lines.append(f"```think\n{rc}\n```\n")
        elif role == "tool":
            lines.append(f"*[工具结果]* {content[:200]}\n")
    md_content = "\n".join(lines)

    if export:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = SAVE_DIR / f"chat_{ts}.md"
        try:
            export_path.write_text(md_content, encoding="utf-8")
            from orca_code.config import console
            console.print(f"[green]已导出: {export_path}[/green]")
            return str(export_path)
        except Exception as e:
            from orca_code.config import console
            console.print(f"[red]导出失败: {e}[/red]")
            return None
    else:
        try:
            (SAVE_DIR / "latest.md").write_text(md_content, encoding="utf-8")
            with open(SAVE_DIR / "chat_history.json", "w", encoding="utf-8") as f:
                json.dump(_sanitize_for_save(session.messages), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.debug("conversation save error: %s", e)
        return None


def auto_save():
    try:
        save_conversation(export=False)
    except Exception as e:
        logging.debug("auto_save failed: %s", e)
