"""orca_code.session_ui — Terminal UI rendering with Rich.

Extracted from session.py. All console output functions.
"""

from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path

from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table

from orca_code.config import (MODEL, BASE_URL, IS_LOCAL, IS_MULTIMODAL,
    ENABLE_THINK_MODE, ENABLE_TTS, ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO,
    VISION_MODEL, TERM_WIDTH, SAVE_DIR, WORKING_DIR, API_KEY, HAS_MEMORY,
    mem_mgr, console, mask_key, PERMISSION_MODE, perm_store)
from orca_code.utils import _sanitize_ansi, _strip_html, _sanitize_for_save
from orca_code.tool_registry import TOOLS, TOOL_MAP
from orca_code.session_messages import _msg_tokens
from orca_code.session_prompt import _estimate_prefix_tokens


def print_gap() -> None:
    try:
        console.print()
        console.print(f"[dim]{'─' * min(TERM_WIDTH, 80)}[/dim]")
        console.print()
    except (KeyboardInterrupt, OSError):
        pass
def print_soft_gap() -> None:
    try:
        console.print()
    except (KeyboardInterrupt, OSError):
        pass
def show_tool_call(name: str, args: dict) -> None:
    try:
        short = json.dumps(args, ensure_ascii=False)
        if len(short) > 55:
            short = short[:52] + '...'
        console.print(f"[bold green]●[/bold green] [#F9F1A5]{name}[/#F9F1A5] [dim]{short}[/dim]")
    except (KeyboardInterrupt, OSError):
        pass
def show_tool_result(result, tool_name=""):
    try:
        if tool_name in ("web_fetch", "read_webpage") and result.startswith("<!DOCTYPE"):
            result = _strip_html(result)
        lines = result.split("\n")
        max_show = len(lines) if tool_name in ("get_weather",) else 15

        # Diff-aware coloring
        _is_diff = tool_name in ("apply_diff", "edit_file") or any(
            line.startswith(("+", "-", "@@")) for line in lines[:3]
        )

        for line in lines[:max_show]:
            if len(line) > TERM_WIDTH:
                line = line[:TERM_WIDTH - 3] + "..."

            if _is_diff and line.startswith("+"):
                console.print(f"[green]  | {line}[/green]")
            elif _is_diff and line.startswith("-"):
                console.print(f"[red]  | {line}[/red]")
            elif _is_diff and line.startswith("@@"):
                console.print(f"[cyan]  | {line}[/cyan]")
            elif line.startswith("[✓") or "✓" in line[:5]:
                console.print(f"[green]  | {line}[/green]")
            elif line.startswith("[✗") or "✗" in line[:5]:
                console.print(f"[red]  | {line}[/red]")
            elif "SECURITY BLOCK" in line:
                console.print(f"[bold red]  | {line}[/bold red]")
            else:
                console.print(f"[dim]  | {line}[/dim]")

        if len(lines) > max_show:
            console.print(f"[dim]  | ... 共 {len(lines)} 行，已截断[/dim]")
    except (KeyboardInterrupt, OSError):
        pass
def show_tool_done(elapsed_ms, parallel=False):
    suffix = " (并行)" if parallel else ""
    try:
        console.print(f"[dim]  └── {elapsed_ms:.0f}ms{suffix}[/dim]")
    except (KeyboardInterrupt, OSError):
        pass
def show_usage(usage):
    if not usage:
        return
    inp = getattr(usage, "prompt_tokens", 0) or 0
    out = getattr(usage, "completion_tokens", 0) or 0
    # [E15] Get server-reported cache and reasoning tokens
    turn_cached = 0
    turn_reasoning = 0
    pd = getattr(usage, 'prompt_tokens_details', None)
    if pd and hasattr(pd, 'cached_tokens'):
        turn_cached = pd.cached_tokens or 0
    cd = getattr(usage, 'completion_tokens_details', None)
    if cd and hasattr(cd, 'reasoning_tokens'):
        turn_reasoning = cd.reasoning_tokens or 0
    hit_rate = (turn_cached / inp * 100) if inp > 0 else 0
    parts = [f"输入 {inp:,}", f"输出 {out:,}", f"合计 {inp + out:,}"]
    if turn_cached > 0:
        parts.append(f"[green]缓存 {turn_cached:,} ({hit_rate:.0f}%)[/green]")
    if turn_reasoning > 0:
        parts.append(f"[yellow]思考 {turn_reasoning:,}[/yellow]")
    console.print(f"[dim][T] {'  |  '.join(parts)}[/dim]")
def show_welcome():
    os.system("cls" if os.name == "nt" else "clear")
    w = min(TERM_WIDTH, 80)
    console.print(f"[blue]{'─' * w}[/blue]")
    console.print(f"[bold blue]{'Orca Code':^{w}}[/bold blue]")
    console.print(f"[blue]{'─' * w}[/blue]")
    gui_status = "on" if ENABLE_GUI_AUTO else "off"
    browser_status = "on" if ENABLE_BROWSER_AUTO else "off"
    mode_str = "[green]本地[/green]" if IS_LOCAL else "[cyan]云端[/cyan]"
    vision_str = ("直接看" if IS_MULTIMODAL else (VISION_MODEL or "需配置"))
    # Permission mode display
    from orca_code.config import PERMISSION_MODE
    perm_label = {"read-only": "🔒只读", "auto": "🛡自动", "yolo": "⚡YOLO"}.get(
        PERMISSION_MODE.value, str(PERMISSION_MODE.value))
    console.print(f"[dim]模式: {mode_str}  |  模型: {MODEL}  |  视觉: {vision_str}  |  权限: {perm_label}[/dim]")
    console.print(f"[dim]思考: {'on' if ENABLE_THINK_MODE else 'off'}  |  "
                  f"工具: {len(_get_tools())}个  |  GUI: {gui_status}  |  浏览器: {browser_status}[/dim]")
    if not IS_LOCAL:
        console.print(f"[dim]API Key: {mask_key(API_KEY)}[/dim]")
    console.print(f"[dim]工作目录: {WORKING_DIR}[/dim]")
    console.print(f"[dim]/help 帮助  |  /clear 清空  |  /stats 统计  |  /save 导出  |  /permissions 权限  |  exit 退出[/dim]")
    if ENABLE_THINK_MODE:
        console.print(f"[dim]💡 思考中可按 Ctrl+C 跳过，直接获取回答[/dim]")
    console.print()
def show_help():
    console.print()
    console.print("[bold]内置命令[/bold]")
    console.print("  /help    显示此帮助")
    console.print("  /clear   清空对话历史")
    console.print("  /stats   显示会话统计")
    console.print("  /save    保存对话到文件（带时间戳）")
    console.print("  /cache   查看 KV 缓存状态")
    console.print("  /think   显示上次思考过程")
    console.print("  /skills  列出已加载技能")
    console.print("  /tasks   列出定时任务")
    console.print("  /memories 查看记忆摘要")
    console.print("  /profile  查看/修改用户画像")
    console.print("  /config   查看/修改配置")
    console.print("  /permissions 查看/管理工具权限")
    console.print("  exit     退出程序")
    console.print()
    console.print("[bold]可用工具[/bold]")
    for name in _get_tool_map():
        console.print(f"  {name}")
def show_stats():
    from orca_code.session import session  # lazy — avoids circular import
    console.print()
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column(style="dim")
    t.add_column()
    t.add_row("对话轮次", str(session.turns))
    t.add_row("工具调用", str(session.tool_calls))
    t.add_row("输入 tokens", f"{session.total_input_tokens:,}")
    t.add_row("输出 tokens", f"{session.total_output_tokens:,}")
    t.add_row("总 tokens", f"{session.total_input_tokens + session.total_output_tokens:,}")
    t.add_row("运行时间", session.elapsed)
    console.print(t)
def show_cache():
    from orca_code.session import session  # lazy — avoids circular import
    prefix = _estimate_prefix_tokens()
    console.print()
    console.print(f"[bold]DeepSeek 磁盘缓存分析[/bold]")
    console.print(f"  固定前缀(system+tools): ~{prefix} tokens")
    console.print(f"  → 这些 tokens 每次请求相同，自动命中磁盘缓存")
    console.print(f"  → 不产生费用，无需重复计算")
    console.print()
    if session.total_cached_tokens > 0:
        hit_rate = session.total_cached_tokens / max(session.total_input_tokens, 1) * 100
        console.print(f"  累计缓存命中: {session.total_cached_tokens:,} tokens ({hit_rate:.0f}%)")
        saved = session.total_cached_tokens / 1_000_000 * 0.14  # ~0.14 RMB per 1M input tokens
        console.print(f"  估算节省: ¥{saved:.4f}")
    else:
        console.print(f"  [dim]等待下一轮请求获取缓存数据...[/dim]")
    console.print()
    console.print(f"[dim]缓存策略: system prompt和tool definitions不变动即可持续命中。[/dim]")
    console.print(f"[dim]每次 /clear 或重启会重建缓存前缀。[/dim]")
