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
from datetime import datetime

from orca_code.config import SAVE_DIR

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

from orca_code.utils import _sanitize_for_save

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
        self.messages: list[dict] = []
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


def export_conversation_html(session_obj=None) -> str | None:
    """Export conversation as a styled HTML page.

    Returns the file path on success, None on failure.
    """
    if session_obj is None:
        session_obj = session

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = SAVE_DIR / f"chat_{ts}.html"

    messages_html = []
    for msg in session_obj.messages:
        role = msg.get("role", "")
        content = (msg.get("content", "") or "").replace("<", "&lt;").replace(">", "&gt;")
        if role == "system":
            continue
        elif role == "user":
            messages_html.append(f'<div class="msg user"><strong>你</strong><p>{content}</p></div>')
        elif role == "assistant":
            rc = msg.get("reasoning_content", "")
            think_html = f'<details class="think"><summary>思考过程</summary><pre>{rc}</pre></details>' if rc else ""
            messages_html.append(
                f'<div class="msg assistant"><strong>助手</strong>{think_html}<p>{content}</p></div>'
            )
        elif role == "tool":
            messages_html.append(
                f'<div class="msg tool"><em>工具: {msg.get("name", "?")}</em>'
                f'<pre>{content[:500]}</pre></div>'
            )

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orca Code — {ts}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;max-width:900px;margin:0 auto;padding:2rem}}
h1{{color:#58a6ff;margin-bottom:1rem}}
.msg{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem;margin-bottom:.75rem}}
.msg.user{{border-left:3px solid #58a6ff}}
.msg.assistant{{border-left:3px solid #3fb950}}
.msg.tool{{border-left:3px solid #d29922;font-size:.85rem}}
.msg strong{{display:block;margin-bottom:.5rem}}
.msg p{{line-height:1.6;white-space:pre-wrap}}
.think{{margin:.5rem 0;padding:.5rem;background:#0d1117;border-radius:4px}}
.think summary{{cursor:pointer;color:#8b949e;font-size:.85rem}}
.think pre{{color:#8b949e;font-size:.8rem;white-space:pre-wrap;margin-top:.5rem}}
pre{{background:#0d1117;padding:.5rem;border-radius:4px;overflow-x:auto;font-size:.85rem}}
.footer{{text-align:center;color:#484f58;margin-top:2rem;font-size:.8rem}}
</style>
</head>
<body>
<h1>🐋 Orca Code 会话</h1>
<p style="color:#8b949e;margin-bottom:1rem">导出时间: {ts} · {session_obj.turns} 轮 · {session_obj.tool_calls} 次工具调用</p>
{"".join(messages_html)}
<div class="footer">Generated by Orca Code v5.3</div>
</body>
</html>"""

    try:
        export_path.write_text(html, encoding="utf-8")
        from orca_code.config import console
        console.print(f"[green]HTML 已导出: {export_path}[/green]")
        return str(export_path)
    except Exception as e:
        from orca_code.config import console
        console.print(f"[red]HTML 导出失败: {e}[/red]")
        return None


def export_conversation_json(session_obj=None) -> str | None:
    """Export conversation as structured JSON with metadata.

    Returns the file path on success, None on failure.
    """
    if session_obj is None:
        session_obj = session

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = SAVE_DIR / f"chat_{ts}.json"

    data = {
        "version": "5.3",
        "exported_at": datetime.now().isoformat(),
        "session": {
            "turns": session_obj.turns,
            "tool_calls": session_obj.tool_calls,
            "total_input_tokens": session_obj.total_input_tokens,
            "total_output_tokens": session_obj.total_output_tokens,
        },
        "messages": _sanitize_for_save(session_obj.messages),
    }

    try:
        export_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        from orca_code.config import console
        console.print(f"[green]JSON 已导出: {export_path}[/green]")
        return str(export_path)
    except Exception as e:
        from orca_code.config import console
        console.print(f"[red]JSON 导出失败: {e}[/red]")
        return None


def export_session(format: str = "markdown", session_obj=None) -> str | None:
    """Export conversation to the specified format.

    Args:
        format: "markdown", "html", or "json"
        session_obj: Session object (default: global session)

    Returns:
        File path on success, None on failure.
    """
    if format == "html":
        return export_conversation_html(session_obj)
    elif format == "json":
        return export_conversation_json(session_obj)
    else:
        return save_conversation(export=True)


def generate_session_title(session_obj=None) -> str:
    """Auto-generate a session title from the first user message (P2-105)."""
    if session_obj is None: session_obj = session
    for m in session_obj.messages:
        if m.get("role") == "user":
            text = (m.get("content", "") or "").strip()
            title = text[:60].replace("\n", " ")
            return title + ("..." if len(text) > 60 else "")
    return "未命名会话"


def get_session_summary(session_obj=None) -> str:
    """Generate a summary of the current session for on-exit display (P2-66)."""
    if session_obj is None:
        session_obj = session
    parts = [
        f"会话统计: {session_obj.turns} 轮对话, {session_obj.tool_calls} 次工具调用",
        f"Token: ↑{session_obj.total_input_tokens:,} ↓{session_obj.total_output_tokens:,}",
    ]
    if session_obj.total_cached_tokens:
        parts.append(f"缓存节省: {session_obj.total_cached_tokens:,} tokens")
    return " · ".join(parts)


def auto_save():
    try:
        save_conversation(export=False)
    except Exception as e:
        logging.debug("auto_save failed: %s", e)

    # Also persist to JSONL (append-only, crash-safe)
    try:
        from orca_code.session_persistence import JSONLSessionStore
        store = JSONLSessionStore(SAVE_DIR / "session.jsonl")
        # Only save the last 2 messages (current user + assistant turn)
        new_msgs = session.messages[-2:] if len(session.messages) >= 2 else session.messages[-1:]
        store.append_messages(new_msgs)
    except Exception as e:
        logging.debug("jsonl_save failed: %s", e)
