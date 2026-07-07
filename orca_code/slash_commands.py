"""orca_code.slash_commands — Unified slash command dispatch.

Extracted from main.py to prevent further growth of the main loop.
All / commands are defined here with help text for /help display.
"""

import json
import logging
from pathlib import Path

from rich.markdown import Markdown

from orca_code.cli.commands import handle_config_cmd, handle_profile_cmd
from orca_code.config import (
    CONFIG,
    ENABLE_VOICE,
    HAS_MEMORY,
    HAS_SPEECH_RECOGNITION,
    PERMISSION_MODE,
    PERMISSION_RULES,
    SPEECH_BACKEND,
    console,
    mem_mgr,
    perm_store,
)
from orca_code.session import (
    build_system_prompt,
    save_conversation,
    session,
    show_cache,
    show_help,
    show_stats,
    show_usage,
)
from orca_code.tool_registry import TOOL_MAP
from orca_code.tools_skills import (
    _autoload_skills_cache,
    _loaded_skills,
    _md_skill_cache,
    _parse_skill_md,
    list_skills,
    list_tasks,
    load_md_skill,
    load_skill,
)
from orca_code.tts_mcp import speak_text, voice_input

logger = logging.getLogger(__name__)

# ─── Help registry ────────────────────────────────────────────────────────────

COMMAND_HELP: dict[str, str] = {
    # System
    "/help": "显示此帮助信息",
    "/clear": "清除当前对话窗口（保留记忆）",
    "/clear --all": "清除对话窗口并清空记忆数据库",
    "/stats": "显示会话统计信息",
    "/save": "保存当前会话",
    "/cache": "显示缓存状态",
    "/think": "显示上一次的思考过程",
    "/search <关键词>": "在对话历史中搜索关键词",
    "/exit": "退出程序",
    # Skills & Tasks
    "/skills": "列出已加载的技能",
    "/tasks": "列出定时任务",
    "/memories": "查看记忆系统状态",
    # Profile & Config
    "/profile <内容>": "更新用户画像",
    "/config [key=value]": "查看或修改配置",
    # Permissions
    "/permissions": "查看权限系统状态",
    "/permissions mode <read-only|auto|yolo>": "切换权限模式",
    "/permissions allow|deny|ask <tool>": "设置工具权限规则",
    "/permissions reset [tool]": "重置权限记忆",
    # TTS & Voice
    "/tts": "测试语音合成",
    "/voice": "启动语音输入",
    # ── Lifecycle commands ──
    "/spec": "启动规格驱动开发 - 写结构化规格说明",
    "/plan": "启动计划与任务分解",
    "/build": "增量实现（/build auto 自动模式）",
    "/test": "测试驱动开发（TDD模式）",
    "/review": "五维代码审查",
    "/code-simplify": "代码简化与复杂度降低",
    "/ship": "发布前检查清单",
    "/webperf": "Web性能审查",
}

LIFECYCLE_SKILL_MAP: dict[str, str] = {
    "/spec": "spec-driven-development",
    "/plan": "planning-and-task-breakdown",
    "/build": "incremental-implementation",
    "/test": "test-driven-development",
    "/review": "code-review-and-quality",
    "/code-simplify": "code-simplification",
    "/ship": "shipping-and-launch",
    "/webperf": "web-performance-audit",
}


def execute_slash_command(user_input: str) -> str | None:
    """Dispatch a slash command. Returns None if not a slash command.

    Args:
        user_input: The raw user input string.

    Returns:
        A result string if the command was handled, None if not a slash command.
        Empty string means "continue loop without additional input".
    """
    if not user_input.startswith("/"):
        return None

    cmd = user_input.lower().strip()

    # ── Lifecycle commands (check first since they're simple dispatch) ─────
    base_cmd = cmd.split()[0] if " " in cmd else cmd
    if base_cmd in LIFECYCLE_SKILL_MAP:
        skill_name = LIFECYCLE_SKILL_MAP[base_cmd]
        if base_cmd == "/build" and len(cmd.split()) > 1 and cmd.split()[1] == "auto":
            return _handle_build_auto()
        result = load_md_skill(skill_name)
        console.print(f"[cyan]{result}[/cyan]")
        return ""

    # ── System commands ────────────────────────────────────────────────────
    if cmd == "/help":
        show_help()
        return ""

    if cmd == "/clear":
        session.messages = [{"role": "system", "content": build_system_prompt()}]
        session.turns = 0
        session.tool_calls = 0
        console.print("[green]Cleared (DB preserved)[/green]")
        return ""

    if cmd == "/clear --all":
        session.messages = [{"role": "system", "content": build_system_prompt()}]
        session.turns = 0
        session.tool_calls = 0
        if HAS_MEMORY and mem_mgr:
            try:
                n = mem_mgr.clear_all()
                console.print(f"[green]Cleared all ({n} messages + meta)[/green]")
            except Exception:
                console.print("[yellow]Cleared window, DB clear failed[/yellow]")
        else:
            console.print("[green]Cleared[/green]")
        return ""

    if cmd == "/stats":
        show_stats()
        return ""

    if cmd == "/save":
        p = save_conversation(export=True)
        from orca_code.session import auto_save
        auto_save()
        if p:
            console.print(f"[dim]Saved: {p}[/dim]")
        return ""

    if cmd == "/cache":
        show_cache()
        return ""

    if cmd == "/think":
        if session.last_thinking:
            console.print()
            console.print("[dim]Last thinking:[/dim]")
            console.print(Markdown(session.last_thinking.strip()))
        else:
            console.print("[dim]No thinking recorded[/dim]")
        return ""

    if cmd == "/skills":
        console.print()
        console.print("[bold]Skills[/bold]")
        if _loaded_skills:
            console.print("[dim]已加载工具技能 (.py):[/dim]")
            for fn, sk in _loaded_skills.items():
                console.print(f"  {fn} (from {sk}.py)")
        else:
            console.print("[dim]已加载工具技能 (.py): (none)[/dim]")
        if _autoload_skills_cache:
            console.print("[dim]已激活行为技能 (.md):[/dim]")
            for sk in sorted(_autoload_skills_cache):
                cached = _md_skill_cache.get(sk, {})
                desc = cached.get("meta", {}).get("description", "")
                label = f"  {sk}"
                if desc:
                    label += f" — {desc}"
                console.print(label)
        else:
            console.print("[dim]已激活行为技能 (.md): (none)[/dim]")
        console.print()
        console.print("[bold]Available:[/bold]")
        console.print(list_skills())
        return ""

    if cmd == "/tasks":
        console.print()
        console.print("[bold]Tasks[/bold]")
        console.print(list_tasks())
        return ""

    if cmd == "/memories":
        console.print()
        console.print("[bold]Memory System[/bold]")
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
        return ""

    if cmd.startswith("/profile"):
        handle_profile_cmd(user_input)
        return ""

    if cmd.startswith("/config"):
        handle_config_cmd(user_input)
        return ""

    # ── Permission commands ────────────────────────────────────────────────
    if cmd == "/permissions":
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
        return ""

    if cmd.startswith("/permissions mode "):
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
        return ""

    if cmd.startswith("/permissions ") and len(cmd.split()) == 3:
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
        return ""

    if cmd.startswith("/permissions reset"):
        parts = cmd.split()
        if len(parts) == 3:
            tool = parts[2]
            perm_store.clear(tool)
            console.print(f"[green]Reset saved choice for: {tool}[/green]")
        else:
            perm_store.clear()
            console.print("[green]All saved permission choices reset[/green]")
        return ""

    # ── Search ─────────────────────────────────────────────────────────────
    if cmd.startswith("/search "):
        kw = cmd[8:].strip().lower()
        found = [m.get('content', '') for m in session.messages
                 if m.get('content') and kw in m.get('content', '').lower()]
        if found:
            console.print(f"[green]{len(found)} matches:[/green]\n" +
                          "\n---\n".join([c[:200] for c in found[:5]]))
        else:
            console.print("[yellow]No matches[/yellow]")
        return ""

    # ── TTS & Voice ────────────────────────────────────────────────────────
    if cmd == "/tts":
        console.print("[cyan]Testing TTS...[/cyan]")
        speak_text("TTS test. Hello world.")
        return ""

    if cmd == "/voice":
        if not ENABLE_VOICE:
            console.print("[yellow]Voice disabled[/yellow]")
        elif not HAS_SPEECH_RECOGNITION:
            console.print("[red]No speech module[/red]")
        else:
            console.print(f"[cyan]Listening... ({SPEECH_BACKEND})[/cyan]")
            r = voice_input()
            if r and r.strip():
                console.print(f"\n[green]Recognized: {r}[/green]")
                return r
            else:
                console.print("[yellow]Nothing recognized[/yellow]")
        return ""

    # ── Unknown ────────────────────────────────────────────────────────────
    console.print(f"[yellow]Unknown: {cmd}[/yellow]")
    return ""


def _handle_build_auto() -> str:
    """Handle /build auto: plan first, then implement."""
    console.print("[cyan]▶ /build auto: 先规划，再实现[/cyan]")
    plan_result = load_md_skill("planning-and-task-breakdown")
    console.print(f"[dim]{plan_result}[/dim]")
    build_result = load_md_skill("incremental-implementation")
    console.print(f"[cyan]{build_result}[/cyan]")
    return ""
