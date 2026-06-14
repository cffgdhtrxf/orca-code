"""orca_code.main — Tool registry, user input, main loop."""

import glob as _glob
import json
import os
import re
import sys
import time
from datetime import datetime

# prompt_toolkit — professional readline replacement (IPython-grade input)
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.formatted_text import FormattedText
from pathlib import Path

import openai

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
from orca_code.tool_registry import TOOL_MAP

# Tool functions are dispatched via TOOL_MAP from tool_registry.
# Only private/internal names imported directly:
from orca_code.tools_skills import (
    _autoload_skills_cache,
    _loaded_skills,
    _md_skill_cache,
    _parse_skill_md,
    _scheduler_shutdown,
    start_scheduler,
)
from orca_code.tts_mcp import init_mcp_tools, speak_text, voice_input
from orca_code.utils import cleanup_temp_files

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
    if not hasattr(session, 'recall_count'):
        session.recall_count = 0
    if session.recall_count >= 3:
        return "Recall limit reached (3 per turn)."
    session.recall_count += 1
    try:
        limit = min(max(1, limit), 20)
        # Use hybrid search (FTS5 + Knowledge Graph) for richer results
        results = mem_mgr.search_hybrid(query, limit=limit, graph_depth=1)
        if not results:
            return "No matching memories found."
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


# TOOLS, TOOL_MAP, run_tool are imported from orca_code.tool_registry
# TOOLS, TOOL_MAP, run_tool are imported from orca_code.tool_registry

# ─── Input history & completion ────────────────────────────────────────────
_INPUT_HISTORY: list[str] = []
_MAX_HISTORY = 200

# Slash commands list (used by completer and help)
_SLASH_COMMANDS = [
    "/help", "/clear", "/stats", "/save", "/cache", "/think",
    "/skills", "/tasks", "/memories", "/profile", "/config",
    "/permissions", "/search", "/tts", "/voice", "/exit",
]


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
    import fnmatch
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
        " Enter 发送  |  Shift+Enter 换行  |  @ 文件  |  / 命令  |  "
        "Ctrl+C 中断  |  Ctrl+D 退出"
    )


_prompt_session: PromptSession | None = None


def _get_prompt_session() -> PromptSession:
    """Create or return the shared prompt_toolkit session."""
    global _prompt_session
    if _prompt_session is None:
        hist_file = SAVE_DIR / ".input_history"
        _prompt_session = PromptSession(
            history=FileHistory(str(hist_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=OrcaCompleter(),
            style=_ORCA_PROMPT_STYLE,
            bottom_toolbar=_get_bottom_toolbar,
            complete_while_typing=False,  # Only on Tab
            reserve_space_for_menu=0,  # No dropdown menu space
            enable_history_search=False,  # We use ↑↓ for history
            multiline=False,  # Enter=submit, Shift+Enter=newline
        )
    return _prompt_session


def get_user_input():
    """Read user input with prompt_toolkit (cursor movement, completions, history).

    Returns:
        User input string, None to exit, "" to skip.
    """
    console.print()
    session = _get_prompt_session()

    # Build prompt text
    prompt_msg = [("class:prompt", "你 > ")]

    try:
        line = session.prompt(
            prompt_msg,
            mouse_support=False,
        )
    except KeyboardInterrupt:
        # Ctrl+C → interrupt current generation (handled by caller)
        console.print("^C")
        return None
    except EOFError:
        # Ctrl+D on empty line → exit
        console.print()
        return None

    if line is None:
        return None

    line = line.rstrip("\r\n")

    if not line.strip():
        return ""

    # Multi-line: if line ends with \\, continue reading
    if line.rstrip().endswith("\\\\"):
        lines = [line.rstrip()[:-2]]
        while True:
            try:
                next_line = session.prompt(
                    [("class:prompt", "  ")],  # Indented continuation
                    mouse_support=False,
                )
                if next_line is None:
                    break
                if next_line.rstrip().endswith("\\\\"):
                    lines.append(next_line.rstrip()[:-2])
                else:
                    lines.append(next_line)
                    break
            except (KeyboardInterrupt, EOFError):
                break
        return "\n".join(lines)

    return line


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
    history_path = SAVE_DIR / "chat_history.json"
    if history_path.exists():
        try:
            with open(history_path, encoding="utf-8") as f:
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
    start_scheduler()
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

        # Track in input history (skip slash commands)
        if not user_input.startswith("/"):
            _add_history(user_input)

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
            elif cmd == "/permissions":
                console.print()
                console.print("[bold]Permission System[/bold]")
                mode_str = {"read-only": "Read Only", "auto": "Auto (ask first time)",
                            "yolo": "YOLO (all allowed)"}.get(
                    PERMISSION_MODE.value, str(PERMISSION_MODE.value))
                console.print(f"  Mode: [cyan]{mode_str}[/cyan]")
                console.print(f"  Saved rules: {len(perm_store._session)} tools")
                if PERMISSION_RULES:
                    console.print("  Config rules:")
                    for k, v in PERMISSION_RULES.items():
                        color = {"allow": "green", "deny": "red", "ask": "yellow"}.get(v, "dim")
                        console.print(f"    [{color}]{k}: {v}[/{color}]")
                console.print()
                console.print("[dim]Commands: /permissions mode <read-only|auto|yolo>[/dim]")
                console.print("[dim]          /permissions allow|deny|ask <tool_name>[/dim]")
                console.print("[dim]          /permissions reset [tool_name][/dim]")
            elif cmd.startswith("/permissions mode "):
                new_mode = cmd.split(" ", 2)[2].strip()
                if new_mode in ("read-only", "auto", "yolo"):
                    CONFIG["permission_mode"] = new_mode
                    try:
                        import orca_code.config as _cfg
                        _cfg.CONFIG_JSON.write_text(
                            json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
                        console.print(f"[green]Mode set to {new_mode} (restart to apply)[/green]")
                    except Exception as e:
                        console.print(f"[red]Save failed: {e}[/red]")
                else:
                    console.print(f"[yellow]Invalid mode: {new_mode}. Use read-only, auto, or yolo.[/yellow]")
            elif cmd.startswith("/permissions ") and len(cmd.split()) == 3:
                _, action, tool = cmd.split()
                if action in ("allow", "deny", "ask"):
                    if tool in TOOL_MAP:
                        PERMISSION_RULES[tool] = action
                        CONFIG["permission_rules"] = PERMISSION_RULES
                        try:
                            import orca_code.config as _cfg
                            _cfg.CONFIG_JSON.write_text(
                                json.dumps(CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
                            color = {"allow": "green", "deny": "red", "ask": "yellow"}[action]
                            console.print(f"[{color}]{tool}: {action} (saved)[/{color}]")
                        except Exception as e:
                            console.print(f"[red]Save failed: {e}[/red]")
                    else:
                        console.print(f"[yellow]Unknown tool: {tool}[/yellow]")
                else:
                    console.print(f"[yellow]Unknown action: {action}. Use allow, deny, or ask.[/yellow]")
            elif cmd.startswith("/permissions reset"):
                parts = cmd.split()
                if len(parts) == 3:
                    tool = parts[2]
                    perm_store.clear(tool)
                    console.print(f"[green]Reset saved choice for: {tool}[/green]")
                else:
                    perm_store.clear()
                    console.print("[green]All saved permission choices reset[/green]")
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
                console.print("[bold red]401: Invalid API key[/bold red]")
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
            else:
                # DeepSeek streaming doesn't include usage — estimate from messages + answer
                est_in = sum(_msg_tokens(m) for m in session.messages[-1:])  # last user msg
                est_out = max(1, len(answer) // 2) if answer else 0  # rough: ~2 chars per token
                session.total_input_tokens += est_in
                session.total_output_tokens += est_out
                console.print(f"[dim][T] 输入 ~{est_in:,}t  |  输出 ~{est_out:,}t (估算)[/dim]")

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
                except Exception:
                    pass

        # Per-turn tokens (diff from cumulative)
        turn_in = session.total_input_tokens - getattr(session, '_prev_in', 0)
        turn_out = session.total_output_tokens - getattr(session, '_prev_out', 0)
        session._prev_in = session.total_input_tokens
        session._prev_out = session.total_output_tokens
        if turn_in <= 0:
            turn_in = sum(_msg_tokens(m) for m in session.messages[-2:])
        if turn_out <= 0:
            turn_out = max(1, len(answer) // 2) if answer else 0
        bal = get_api_balance()

        # Single-line turn summary
        from orca_code.session_ui import show_turn_summary
        show_turn_summary(
            turn=session.turns,
            input_tokens=turn_in,
            output_tokens=turn_out,
            elapsed=session.elapsed,
            balance=bal,
        )

if __name__ == "__main__":
    main()
