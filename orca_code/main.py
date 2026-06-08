"""orca_code.main — Tool registry, user input, main loop."""

import os, sys, json, re, time, unicodedata, inspect
import base64
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from orca_code.config import (CONFIG, SCRIPT_DIR, SAVE_DIR, TEMP_DIR,
    SKILLS_DIR, WORKING_DIR, HAS_MEMORY, HAS_SPEECH_RECOGNITION,
    ENABLE_VOICE, ENABLE_TTS, HAS_TTS, SPEECH_BACKEND,
    ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO,
    IS_MULTIMODAL, MODEL, BASE_URL, API_KEY, TERM_WIDTH,
    mem_mgr, console, client, mask_key, get_api_balance,
    PERMISSION_MODE, PERMISSION_RULES, perm_store)
from orca_code.cli.commands import handle_config_cmd, handle_profile_cmd
# Tool functions are dispatched via TOOL_MAP from tool_registry.
# Only private/internal names imported directly:
from orca_code.tools_skills import (_loaded_skills, _md_skill_cache,
    _autoload_skills_cache, _parse_skill_md, _scheduler_shutdown, _scheduler_thread,
    start_scheduler)
from orca_code.tts_mcp import (speak_text, voice_input, init_mcp_tools,
    init_speech_recognition)
from orca_code.session import (
    session, build_system_prompt, sanitize_messages, smart_trim_messages,
    call_model, process_stream, execute_tool_calls,
    show_welcome, show_help, show_stats, show_cache, show_usage,
    print_gap, print_soft_gap, auto_save, save_conversation,
    _msg_tokens,
)
from orca_code.utils import (_estimate_tokens, cleanup_temp_files, resolve_tool_path)
from orca_code.tool_registry import TOOLS, TOOL_MAP, run_tool
from orca_code.subagent import agent_open, agent_eval, agent_close
from orca_code.lsp import lsp_diagnostics, lsp_references, lsp_definition, auto_diagnose, get_pending_diagnostics, shutdown_all

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
        results = mem_mgr.search_with_snippet(query, limit=limit, snippet_chars=150)
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
