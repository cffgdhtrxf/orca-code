"""orca_code.main — Tool registry, user input, main loop."""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import openai

# prompt_toolkit — professional readline replacement (IPython-grade input)
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.formatted_text import HTML as PtHTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.markdown import Markdown

from orca_code.cli.commands import handle_config_cmd, handle_profile_cmd
from orca_code.config import (
    CONFIG,
    ENABLE_TTS,
    ENABLE_VOICE,
    HAS_MEMORY,
    HAS_SPEECH_RECOGNITION,
    HAS_TTS,
    IS_MULTIMODAL,
    MODEL,
    PERMISSION_MODE,
    PERMISSION_RULES,
    SAVE_DIR,
    SKILLS_DIR,
    SPEECH_BACKEND,
    client,
    console,
    get_api_balance,
    mem_mgr,
    perm_store,
)
from orca_code.lsp import (
    get_pending_diagnostics,
)
from orca_code.session import (
    _msg_tokens,
    auto_save,
    build_system_prompt,
    call_model,
    execute_tool_calls,
    print_gap,
    print_soft_gap,
    process_stream,
    sanitize_messages,
    save_conversation,
    session,
    show_cache,
    show_help,
    show_stats,
    show_usage,
    show_welcome,
    smart_trim_messages,
)
from orca_code.tool_registry import TOOL_MAP, run_tool

# Tool functions are dispatched via TOOL_MAP from tool_registry.
# Only private/internal names imported directly:
from orca_code.tools_skills import (
    _autoload_skills_cache,
    _loaded_skills,
    _md_skill_cache,
    _parse_skill_md,
    _scheduler_shutdown,
    load_md_skill,
    start_scheduler,
)
from orca_code.mcp_client import get_mcp_registry, load_mcp_configs_with_fallback
from orca_code.tts_mcp import speak_text, voice_input
from orca_code.utils import cleanup_temp_files

try:
    from _python_repl import execute_python
    HAS_PYTHON_REPL = True
except ImportError:
    HAS_PYTHON_REPL = False
    def execute_python(code, timeout=30): return "REPL not available"

from orca_code.slash_commands import COMMAND_HELP, execute_slash_command
from orca_code.tools_memory import recall_conversation, update_profile, inject_session as _inject_memory_session


# TOOLS, TOOL_MAP, run_tool are imported from orca_code.tool_registry -- see above

# ─── Input history & completion ────────────────────────────────────────────
_INPUT_HISTORY: list[str] = []
_MAX_HISTORY = 200

# ─── Terminal resize detection ─────────────────────────────────────────────
# cmd.exe toggles its screen buffer on Alt+Enter (windowed ↔ fullscreen),
# which invalidates prompt_toolkit's cached dimensions.  We poll terminal
# size before each prompt and recreate the PromptSession when it changes.
import time as _time

_last_term_cols: int = 0
_last_term_rows: int = 0
_last_resize_check: float = 0.0
_RESIZE_COOLDOWN: float = 0.2       # 200 ms debounce
_RESIZE_THRESHOLD: int = 2           # minimum col/row change to trigger


def _check_terminal_resize() -> bool:
    """Poll terminal size.  Returns True when dimensions changed significantly.

    Debounced (200 ms) to avoid reacting to intermediate resize states.
    First call seeds the baseline without triggering.
    """
    global _last_term_cols, _last_term_rows, _last_resize_check
    now = _time.monotonic()
    if now - _last_resize_check < _RESIZE_COOLDOWN:
        return False
    _last_resize_check = now
    try:
        size = os.get_terminal_size()
        cols, rows = size.columns, size.lines
    except Exception:
        return False
    if _last_term_cols == 0:
        _last_term_cols, _last_term_rows = cols, rows
        return False
    if abs(cols - _last_term_cols) >= _RESIZE_THRESHOLD or abs(rows - _last_term_rows) >= _RESIZE_THRESHOLD:
        _last_term_cols, _last_term_rows = cols, rows
        return True
    return False

# Slash commands list (used by completer and help)
_SLASH_COMMANDS = sorted(COMMAND_HELP.keys())


class OrcaCompleter(Completer):
    """@ file mentions + / command completions + Tab path completion."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # / command completion
        if text.lstrip().startswith("/"):
            # Find the token starting with /
            for i in range(len(text) - 1, -1, -1):
                if text[i] == "/" and (i == 0 or text[i - 1].isspace()):
                    token = text[i:]
                    for cmd in _SLASH_COMMANDS:
                        if cmd.startswith(token):
                            yield Completion(
                                cmd,
                                start_position=-len(token),
                                display_meta="command",
                            )
                    return

        # @ file mention completion
        at_pos = text.rfind("@")
        if at_pos >= 0 and (at_pos == 0 or text[at_pos - 1].isspace()):
            query = text[at_pos + 1:]
            matches = _fuzzy_match_files(query)
            for m in matches[:12]:
                display = m
                if os.path.isdir(os.path.join(os.getcwd(), m.rstrip("/").rstrip("\\"))):
                    display = m.rstrip("/").rstrip("\\") + "/"
                yield Completion(
                    display,
                    start_position=-len(query),
                    display_meta="file" if not m.endswith("/") else "dir",
                )
            return

        # Fallback: path completion (Tab)
        yield from PathCompleter(
            expanduser=True,
            file_filter=lambda name: not name.startswith("."),
        ).get_completions(document, complete_event)


def _fuzzy_match_files(query: str, max_results: int = 12) -> list[str]:
    """Fuzzy match files in current directory for @ mentions."""
    results = []
    try:
        for entry in os.scandir(os.getcwd()):
            if entry.name.startswith("."):
                continue
            name = entry.name
            if entry.is_dir():
                name += os.sep
            # Simple substring match (case-insensitive)
            if query.lower() in name.lower():
                # Score: exact prefix match ranks higher
                score = 0 if name.lower().startswith(query.lower()) else 1
                results.append((score, name))
    except OSError:
        pass
    results.sort(key=lambda x: (x[0], len(x[1])))
    return [r[1] for r in results[:max_results]]


# ── prompt_toolkit session (reused across turns) ────────────────────────

_ORCA_PROMPT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "bottom-toolbar": "dim italic",
    "auto-suggestion": "#666666",
})


def _get_bottom_toolbar():
    """Footer bar like DeepCode with flash status integration."""
    from orca_code.session_ui import _get_flash
    flash_msg, flash_style = _get_flash()
    if flash_msg:
        return f" {flash_msg} "
    return (
        " Enter 发送  |  Ctrl+Enter 换行  |  @ 文件  |  / 命令  |  "
        "Ctrl+C 中断  |  Ctrl+D 退出"
    )


_session_history: InMemoryHistory | None = None


def _get_session_history() -> InMemoryHistory:
    global _session_history
    if _session_history is None:
        _session_history = InMemoryHistory()
    return _session_history


_file_history: FileHistory | None = None


def _get_file_history() -> FileHistory:
    global _file_history
    if _file_history is None:
        hist_file = SAVE_DIR / ".input_history"
        _file_history = FileHistory(str(hist_file))
    return _file_history


_kb = KeyBindings()


@_kb.add("enter")
def _enter_submit(event):
    """Enter submits the input."""
    event.current_buffer.validate_and_handle()


@_kb.add("c-m")
def _ctrl_enter_newline(event):
    """Ctrl+Enter / Ctrl+M inserts a newline for multi-line input.

    On Windows Terminal, Ctrl+Enter sends ESC[27;5;13~ which
    prompt_toolkit parses as Keys.ControlM ('c-m'). Regular Enter
    sends 'enter', so the two are distinguishable. This gives us
    the user-requested Ctrl+Enter = newline behavior.

    On legacy cmd.exe / PowerShell 5.x consoles, Ctrl+Enter may
    not send a distinct sequence and falls through as 'enter'.
    Users on those terminals can use \\ (backslash) at end of line
    for continuation, or Ctrl+J (line feed) to insert a newline.
    """
    event.current_buffer.insert_text("\n")


@_kb.add("c-j")
def _ctrl_j_newline(event):
    """Ctrl+J (Line Feed) inserts a newline — fallback for terminals
    where Ctrl+Enter is indistinguishable from Enter."""
    event.current_buffer.insert_text("\n")


_prompt_session: PromptSession | None = None


def _get_prompt_session() -> PromptSession:
    """Create or return the shared prompt_toolkit session.

    Key design: multiline=True with custom key bindings.
    - Enter: submit (send to AI)
    - Ctrl+Enter (c-m): insert newline (multi-line input)
    - Ctrl+J (c-j): insert newline (fallback for legacy terminals)
    - IME composing Enter: passed to IME naturally — prompt_toolkit's
      multiline mode does NOT steal Enter from IME the way multiline=False
      does, because the buffer accepts newlines and the IME candidate
      window handles Enter for composition before it reaches the key binding.

    This fixes the IME conflict where text disappears when Chinese/Japanese/
    Korean input methods try to use Enter for candidate selection.
    """
    global _prompt_session
    if _prompt_session is None:
        _prompt_session = _build_prompt_session()
    return _prompt_session


def _build_prompt_session() -> PromptSession:
    """Build a fresh PromptSession with current terminal dimensions.

    Extracted so _recreate_prompt_session can re-build after resize
    without duplicating configuration.
    """
    return PromptSession(
        history=_get_file_history(),
        auto_suggest=AutoSuggestFromHistory(),
        completer=OrcaCompleter(),
        style=_ORCA_PROMPT_STYLE,
        bottom_toolbar=_get_bottom_toolbar,
        key_bindings=_kb,
        complete_while_typing=False,
        reserve_space_for_menu=0,
        enable_history_search=False,
        multiline=True,
        vi_mode=False,
        prompt_continuation="  ",
    )


def _recreate_prompt_session() -> None:
    """Recreate the PromptSession after terminal resize.

    cmd.exe Alt+Enter destroys/recreates the console screen buffer.
    prompt_toolkit caches the old buffer handle internally, so we must
    build a fresh session that queries the new buffer's dimensions.

    History (FileHistory + InMemoryHistory) is preserved via singleton
    accessors — they survive session recreation.
    """
    global _prompt_session
    old = _prompt_session
    try:
        _prompt_session = _build_prompt_session()
    except Exception:
        _prompt_session = old  # restore on failure — no regression


def get_user_input():
    """Read user input with prompt_toolkit.

    Multi-line input via Ctrl+Enter (Windows Terminal) or Ctrl+J (fallback).
    Enter submits. Backslash at end of line also continues.

    Detects terminal resize (cmd.exe Alt+Enter windowed ↔ fullscreen) and
    recreates the PromptSession to pick up the new console buffer dimensions.

    Returns:
        User input string, None to exit, "" to skip.
    """
    # Detect terminal resize (e.g. cmd.exe Alt+Enter toggle)
    if _check_terminal_resize():
        # Stabilize ANSI state machine before clearing
        sys.stdout.write("\033[0m\033[0m\033[0m")
        sys.stdout.flush()
        console.clear()
        _recreate_prompt_session()

    console.print()
    session = _get_prompt_session()

    try:
        u_in = session.prompt(
            [("class:prompt", "你 > ")],
            mouse_support=False,
        )
    except KeyboardInterrupt:
        console.print("^C")
        return None
    except EOFError:
        console.print()
        return None

    if u_in is None:
        return None

    u_in = u_in.rstrip("\r\n")

    if not u_in.strip():
        return ""

    return u_in


def _add_history(line: str):
    """Append to in-memory history (FileHistory handles disk persistence)."""
    if _INPUT_HISTORY and _INPUT_HISTORY[-1] == line:
        return
    _INPUT_HISTORY.append(line)
    if len(_INPUT_HISTORY) > _MAX_HISTORY:
        _INPUT_HISTORY.pop(0)


def _search_history(query: str) -> list[str]:
    """Search in-memory history (legacy, kept for API compat)."""
    q = query.lower()
    return [line for line in reversed(_INPUT_HISTORY) if q in line.lower()][:10]


def _complete_path(partial: str) -> str | None:
    """Legacy path completion (replaced by OrcaCompleter, kept for API compat)."""
    return None


def main():
    loaded_msgs: list | None = None
    history_path = SAVE_DIR / "chat_history.json"

    # Try L1: full chat_history.json
    if history_path.exists():
        try:
            with open(history_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list) and len(loaded) > 0:
                if loaded[0].get("role") != "system":
                    raise ValueError("Bad history: first msg not system")
                # Soft match: only check Constitution prefix (stable), not full prompt
                cur_prompt = build_system_prompt()
                if not loaded[0].get("content", "").startswith(cur_prompt[:80]):
                    raise ValueError("System prompt prefix mismatch")
                loaded[0]["content"] = cur_prompt  # update to current system prompt
                loaded_msgs = sanitize_messages(loaded)
                console.print(f"[green]Loaded history ({len(loaded_msgs)} msgs)[/green]")
        except Exception as e:
            console.print(f"[yellow]chat_history.json load failed: {e}, trying JSONL...[/yellow]")

    # Try L2 fallback: session.jsonl (incremental, crash-safe)
    if loaded_msgs is None:
        try:
            from orca_code.session_persistence import JSONLSessionStore
            store = JSONLSessionStore(SAVE_DIR / "session.jsonl")
            recent = store.tail_as_messages(50)
            if recent:
                loaded_msgs = [{"role": "system", "content": build_system_prompt()}]
                for m in recent:
                    m.pop("timestamp", None)
                    loaded_msgs.append(m)
                console.print(f"[green]Recovered from JSONL ({len(loaded_msgs)} msgs)[/green]")
        except Exception:
            pass

    if loaded_msgs:
        session.messages = loaded_msgs
    else:
        session.messages = [{"role": "system", "content": build_system_prompt()}]
        # L3: inject rolling summary from persistent memory (cross-session)
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

    # If no API key configured, print setup guide and exit
    if client is None:
        import orca_code.config as _cfg
        console.print()
        console.print("[bold yellow]╔══════════════════════════════════════════════════╗[/bold yellow]")
        console.print("[bold yellow]║        首次启动 — 需要配置 API 密钥            ║[/bold yellow]")
        console.print("[bold yellow]╚══════════════════════════════════════════════════╝[/bold yellow]")
        console.print()
        console.print(f"  已自动创建配置文件: [cyan]{_cfg.CONFIG_JSON}[/cyan]")
        console.print()
        console.print("  请编辑 [cyan]config.json[/cyan] 填入以下字段：")
        console.print()
        console.print('  [green]api_key[/green]        — LLM API 密钥 (必填，如 DeepSeek sk-...)')
        console.print('  [green]tavily_api_key[/green]  — 搜索 API 密钥 (可选，搜索功能需要)')
        console.print()
        console.print("  也可以设置环境变量：")
        console.print("  [dim]ORCA_API_KEY=sk-xxx[/dim]")
        console.print("  [dim]ORCA_TAVILY_KEY=tvly-xxx[/dim]")
        console.print()
        console.print(f"  配置完成后重新运行 [cyan]start.bat[/cyan] 即可。")
        console.print()
        return

    mcp_registry = get_mcp_registry()
    mcp_configs = load_mcp_configs_with_fallback(CONFIG)
    for cfg in mcp_configs:
        mcp_registry.add_server(cfg)
    if mcp_configs:
        results = mcp_registry.connect_all()
        mcp_count = sum(1 for v in results.values() if v)
    else:
        mcp_count = 0
    last_request_time = 0
    if HAS_MEMORY and mem_mgr:
        _inject_memory_session(mem_mgr, session)
    show_welcome()
    start_scheduler()
    if mcp_count:
        console.print(f"[dim]MCP: {mcp_count} external tools loaded[/dim]")

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

        # Track in input history (skip slash commands)
        if not user_input.startswith("/"):
            _add_history(user_input)

        slash_result = execute_slash_command(user_input)
        if slash_result is not None:
            if isinstance(slash_result, str) and slash_result:
                user_input = slash_result
            else:
                continue

        # ---- Auto-trigger SKILL.md matching (scans all subdirectories for lifecycle skills) ----
        # Uses word-boundary matching to avoid false positives on common words.
        # English triggers get \b word boundaries; Chinese triggers need ≥3 chars.
        for md_file in sorted(SKILLS_DIR.glob("**/*.md")):
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
                # Regex trigger — use as-is, user wrote it deliberately
                if any(c in trigger for c in ('.*', '^', '$', '\\d', '\\w', '|', '[', ']', '(', ')')):
                    try:
                        if re.search(trigger, user_input, re.IGNORECASE):
                            hit = True
                    except re.error:
                        pass
                else:
                    # Minimum 2 chars to avoid single-char false positives.
                    if len(trigger) < 2:
                        continue
                    # ASCII triggers (≥4 chars to avoid false positives on
                    # short common words like API, Git, TDD, CI, CD).
                    # Uses \b with re.ASCII so Chinese chars are non-word,
                    # correctly handling "帮我写个spec" → match.
                    if trigger.isascii():
                        # ASCII triggers ≥4 chars with \b word boundaries.
                        # This correctly handles mixed CJK+English ("帮我写个spec").
                        if len(trigger) >= 4 and re.search(
                            r'\b' + re.escape(trigger) + r'\b',
                            user_input, re.IGNORECASE | re.ASCII,
                        ):
                            hit = True
                    elif len(trigger) >= 2:
                        # CJK triggers ≥2 chars: manual word-boundary check.
                        # Matches when NOT embedded in CJK text on both sides.
                        # e.g. "代码需要重构" → 重构 at end → match.
                        #      "最需要的升级是什么" → 升级 in middle → no match.
                        def _is_cjk(c):
                            return '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f'
                        idx = user_input.lower().find(trigger.lower())
                        while idx >= 0:
                            before = user_input[idx - 1] if idx > 0 else ' '
                            after = user_input[idx + len(trigger)] if idx + len(trigger) < len(user_input) else ' '
                            if not (_is_cjk(before) and _is_cjk(after)):
                                hit = True
                                break
                            idx = user_input.lower().find(trigger.lower(), idx + 1)
                if hit:
                    console.print(f"[dim]触发技能: {name}[/dim]")
                    load_md_skill(name)
                    phase = parsed["meta"].get("phase", "")
                    if phase:
                        console.print(f"[dim]  当前阶段: {phase}[/dim]")
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
        t0 = time.time()  # per-turn elapsed timer
        if not hasattr(session, 'recall_count'):
            session.recall_count = 0
        session.recall_count = 0
        generated_files = set()
        reasoning = ""
        answer = ""
        turn_tool_count = 0
        turn_cached = 0
        turn_reasoning = 0

        while True:
            session.messages = sanitize_messages(session.messages)
            session.messages = smart_trim_messages(session.messages, llm_client=client, llm_model=MODEL)
            try:
                stream = call_model(session.messages)
            except openai.NotFoundError as e:
                console.print(f"[bold red]404: Model '{MODEL}' not found[/bold red]")
                logging.error(f"Model: {e}"); session.messages.pop(); session.turns -= 1; break
            except openai.AuthenticationError as e:
                console.print("[bold red]401: Invalid API key[/bold red]")
                logging.error(f"Auth: {e}"); session.messages.pop(); session.turns -= 1; break
            except openai.BadRequestError as e:
                console.print(f"[bold red]400: {e}[/bold red]")
                logging.error(f"BadReq: {e}"); session.messages.pop(); session.turns -= 1; break
            except openai.APIStatusError as e:
                if e.status_code == 402:
                    console.print("[bold red]402: API 余额不足，请前往 https://platform.deepseek.com 充值[/bold red]")
                else:
                    console.print(f"[bold red]API Error ({e.status_code}): {e}[/bold red]")
                logging.error(f"APIStatus: {e}"); session.messages.pop(); session.turns -= 1; break
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
                session.add_usage(usage)
                # Accumulate per-turn cached & reasoning tokens
                hit = getattr(usage, 'prompt_cache_hit_tokens', 0) or 0
                pd = getattr(usage, 'prompt_tokens_details', None)
                if pd and hasattr(pd, 'cached_tokens'):
                    hit += (pd.cached_tokens or 0)
                turn_cached += hit
                cd = getattr(usage, 'completion_tokens_details', None)
                if cd and hasattr(cd, 'reasoning_tokens'):
                    turn_reasoning += (cd.reasoning_tokens or 0)
                show_usage(usage)
            else:
                # No usage returned by API — do not fabricate estimates
                console.print("[dim][T] Token 用量: N/A (API 未返回 usage)[/dim]")

            if tool_calls_idx:
                tc_list, tr_list = execute_tool_calls(tool_calls_idx)
                turn_tool_count += len(tc_list)
                for tc in tc_list:
                    if tc['function']['name'] in ('write_file','write_excel','write_word','take_screenshot'):
                        try:
                            generated_files.add(str(Path(json.loads(tc['function']['arguments'])['path']).resolve()))
                        except Exception:
                            logging.exception("Failed to track generated file for %s", tc['function']['name'])
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
                        clean = re.sub(r'!\[.*?\]\(.*?\)','',clean)
                        clean = re.sub(r'\[(.+?)\]\(.+?\)',r'\1',clean)
                        clean = re.sub(r'\*\*(.+?)\*\*',r'\1',clean)
                        clean = re.sub(r'`(.+?)`',r'\1',clean)
                        clean = re.sub(r'^#{1,6}\s+','',clean,flags=re.MULTILINE)
                        clean = re.sub(r'^\s*[-*+]\s+','',clean,flags=re.MULTILINE)
                        clean = re.sub(r'\n{3,}','\n\n',clean); clean = clean.strip()
                        if clean: speak_text(clean)
                    except Exception as _tts_err:
                        logging.exception("TTS failed")

            session.messages.append({
                "role":"assistant","content":answer,"reasoning_content":reasoning})
            break

        cleaned = cleanup_temp_files(generated_files)
        if cleaned: console.print(f"[dim]  {cleaned}[/dim]")

        # Flush pending LSP diagnostics from edits
        try:
            diags = get_pending_diagnostics()
            if diags:
                console.print(f"[dim yellow]{diags}[/dim yellow]")
        except Exception:
            pass

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
                    # Auto-extract entities into knowledge graph
                    mem_mgr.auto_extract_knowledge(str(last_user)[:5000])
                    # Persist rolling summary for cross-session context
                    try:
                        mem_mgr.set_meta("rolling_summary", str(last_user)[:200])
                        mem_mgr.set_meta("rolling_summary_range", datetime.now().strftime("%Y-%m-%d"))
                    except Exception:
                        pass
                except Exception:
                    pass

        # Per-turn tokens (diff from cumulative)
        turn_in = session.total_input_tokens - getattr(session, '_prev_in', 0)
        turn_out = session.total_output_tokens - getattr(session, '_prev_out', 0)
        session._prev_in = session.total_input_tokens
        session._prev_out = session.total_output_tokens
        bal = get_api_balance()

        # Per-turn elapsed
        turn_elapsed = f"{time.time() - t0:.1f}s"

        # Single-line turn summary (new19.py style)
        from orca_code.session_ui import show_turn_summary
        show_turn_summary(
            turn=session.turns,
            input_tokens=turn_in,
            output_tokens=turn_out,
            elapsed=turn_elapsed,
            balance=bal,
            tool_count=turn_tool_count,
            cached_tokens=turn_cached,
            reasoning_tokens=turn_reasoning,
            ttl_warning=ttl_warning,
        )

if __name__ == "__main__":
    main()
