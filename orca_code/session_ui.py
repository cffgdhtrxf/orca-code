"""orca_code.session_ui — Terminal UI rendering with Rich.

Extracted from session.py. All console output functions.
"""

from __future__ import annotations

import json
import os
import sys

# ─── Flash status messages (auto-dismiss after 2.5s, like DeepCode) ─────
import threading as _threading

from rich.markdown import Markdown
from rich.table import Table

from orca_code.config import (
    API_KEY,
    ENABLE_BROWSER_AUTO,
    ENABLE_GUI_AUTO,
    ENABLE_THINK_MODE,
    IS_LOCAL,
    IS_MULTIMODAL,
    MODEL,
    PERMISSION_MODE,
    TERM_WIDTH,
    VISION_MODEL,
    WORKING_DIR,
    console,
)
from orca_code.infrastructure.config_loader import mask_key
from orca_code.session_messages import _get_tools
from orca_code.session_prompt import _estimate_prefix_tokens
from orca_code.utils import _strip_html

_flash_msg: str | None = None
_flash_style: str = "dim"
_flash_timer: _threading.Timer | None = None
_flash_lock = _threading.Lock()


def flash_status(msg: str, style: str = "dim"):
    """Show a status message that auto-clears after 2.5s.

    Thread-safe. Used for transient feedback like "已打断", "已清空".
    """
    global _flash_msg, _flash_style, _flash_timer

    def _clear():
        global _flash_msg
        with _flash_lock:
            _flash_msg = None

    with _flash_lock:
        _flash_msg = msg
        _flash_style = style
        if _flash_timer:
            _flash_timer.cancel()
        _flash_timer = _threading.Timer(2.5, _clear)
        _flash_timer.daemon = True
        _flash_timer.start()


def _get_flash() -> tuple[str | None, str]:
    """Get current flash message (if any) and its style. Thread-safe."""
    with _flash_lock:
        return _flash_msg, _flash_style


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
_LOGO_LINES = [
    " ██████╗ ██████╗  ██████╗ █████╗          ██████╗ ██████╗ ██████╗ ███████╗",
    "██╔═══██╗██╔══██╗██╔════╝██╔══██╗        ██╔════╝██╔═══██╗██╔══██╗██╔════╝",
    "██║   ██║██████╔╝██║     ███████║        ██║     ██║   ██║██║  ██║█████╗",
    "██║   ██║██╔══██╗██║     ██╔══██║        ██║     ██║   ██║██║  ██║██╔══╝",
    "╚██████╔╝██║  ██║╚██████╗██║  ██║        ╚██████╗╚██████╔╝██████╔╝███████╗",
    " ╚═════╝ ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝         ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝",
]

# Gradient colors: deep blue → light cyan (#229AC3 → #61D6D6)
_GRAD_START = (34, 154, 195)
_GRAD_END = (97, 214, 214)

_TIPS = [
    ("/help", "查看所有命令和工具"),
    ("/clear", "清空对话历史，释放上下文"),
    ("/stats", "查看会话统计和 token 用量"),
    ("/save", "导出对话到 Markdown 文件"),
    ("/think", "查看上次思考过程"),
    ("Ctrl+C", "中断当前生成 / 跳过思考"),
    ("Tab", "自动补全文件路径"),
    ("Ctrl+R", "搜索输入历史"),
    ("/config", "查看或修改配置"),
    ("exit", "退出程序"),
]

import random as _random


def show_welcome():
    os.system("cls" if os.name == "nt" else "clear")
    w = min(TERM_WIDTH, 80)

    # ── Logo (diagonal gradient: #229AC3 → #61D6D6) ──────────────────
    # Use raw ANSI for max compatibility (same as orca_code_banner.py).
    # Bypasses Rich's GBK-limited legacy Windows renderer.
    sr, sg, sb = _GRAD_START
    er, eg, eb = _GRAD_END
    n_rows = len(_LOGO_LINES)
    for i, line in enumerate(_LOGO_LINES):
        n_cols = len(line)
        for j, ch in enumerate(line):
            if ch == " ":
                sys.stdout.write(" ")
                continue
            t = (i / max(n_rows - 1, 1) + j / max(n_cols - 1, 1)) / 2
            r = int(sr + (er - sr) * t)
            g = int(sg + (eg - sg) * t)
            b = int(sb + (eb - sb) * t)
            sys.stdout.write(f"\033[38;2;{r};{g};{b}m\033[1m{ch}")
        sys.stdout.write("\033[0m\n")
    sys.stdout.flush()

    # ── Version line ──────────────────────────────────────────────────
    console.print(f"[dim]{( 'v5.2' ):>{w}}[/dim]")
    console.print()

    # ── Config Panel ──────────────────────────────────────────────────
    gui_status = "on" if ENABLE_GUI_AUTO else "off"
    browser_status = "on" if ENABLE_BROWSER_AUTO else "off"
    mode_str = "本地" if IS_LOCAL else "云端"
    mode_color = "green" if IS_LOCAL else "cyan"
    vision_str = "直接看" if IS_MULTIMODAL else (VISION_MODEL or "需配置")
    perm_label = {"read-only": "🔒 只读", "auto": "🛡 自动", "yolo": "⚡ YOLO"}.get(
        PERMISSION_MODE.value, str(PERMISSION_MODE.value))

    # Build config rows with label/value alignment
    rows = [
        ("模型", f"[{mode_color}]{MODEL}[/{mode_color}]"),
        ("模式", f"[{mode_color}]{mode_str}[/{mode_color}]"),
        ("视觉", vision_str),
        ("思考", "on" if ENABLE_THINK_MODE else "off"),
        ("权限", perm_label),
        ("工具", f"{len(_get_tools())} 个"),
        ("GUI", gui_status),
        ("工作目录", str(WORKING_DIR)),
    ]
    if not IS_LOCAL:
        rows.append(("API Key", mask_key(API_KEY)))

    # Two approaches based on terminal width
    if w >= 72:
        # Wide: config panel
        col_w = max(len(k) for k, _ in rows)
        lines = []
        for k, v in rows:
            lines.append(f"  [dim]{k:>{col_w}}[/dim]  {v}")
        panel = Panel(
            "\n".join(lines),
            border_style="cyan",
            padding=(1, 2),
        )
        console.print(panel)
    else:
        # Narrow: simple list
        for k, v in rows:
            console.print(f"  [dim]{k}:[/dim] {v}")

    console.print()

    # ── Quick Commands ────────────────────────────────────────────────
    console.print("[dim]快捷命令:[/dim]  "
                  "/help  /clear  /stats  /save  /config  /permissions  exit")
    console.print("[dim]快捷键:[/dim]    "
                  "Ctrl+C 中断  Tab 补全  Ctrl+R 搜索历史")

    # ── Random Tip ────────────────────────────────────────────────────
    tip_key, tip_desc = _random.choice(_TIPS)
    console.print(f"[dim]💡 {tip_key} — {tip_desc}[/dim]")

    if ENABLE_THINK_MODE:
        console.print("[dim]💭 思考中可按 Ctrl+C 跳过，直接获取回答[/dim]")
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
    console.print("[bold]DeepSeek 磁盘缓存分析[/bold]")
    console.print(f"  固定前缀(system+tools): ~{prefix} tokens")
    console.print("  → 这些 tokens 每次请求相同，自动命中磁盘缓存")
    console.print("  → 不产生费用，无需重复计算")
    console.print()
    if session.total_cached_tokens > 0:
        hit_rate = session.total_cached_tokens / max(session.total_input_tokens, 1) * 100
        console.print(f"  累计缓存命中: {session.total_cached_tokens:,} tokens ({hit_rate:.0f}%)")
        saved = session.total_cached_tokens / 1_000_000 * 0.14  # ~0.14 RMB per 1M input tokens
        console.print(f"  估算节省: ¥{saved:.4f}")
    else:
        console.print("  [dim]等待下一轮请求获取缓存数据...[/dim]")
    console.print()
    console.print("[dim]缓存策略: system prompt和tool definitions不变动即可持续命中。[/dim]")
    console.print("[dim]每次 /clear 或重启会重建缓存前缀。[/dim]")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase UI-1: Enhanced rendering — code highlight, diff, thinking, status
# ═══════════════════════════════════════════════════════════════════════════════

import re

from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

# Regex for fenced code blocks: ```lang\n code \n```
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def render_markdown_smart(text: str):
    """Render markdown with syntax-highlighted code blocks.

    Detects ```python, ```json, ```diff, etc. and uses Rich Syntax
    for proper highlighting instead of plain monospace.
    """
    if not _CODE_BLOCK_RE.search(text):
        # No code blocks — use plain Markdown
        return Markdown(text, code_theme="monokai")

    # Split into segments: text / code_block / text / code_block ...
    parts = []
    last_end = 0
    for match in _CODE_BLOCK_RE.finditer(text):
        # Text before this code block
        before = text[last_end:match.start()]
        if before.strip():
            parts.append(Markdown(before, code_theme="monokai"))

        # Code block with syntax highlighting
        lang = match.group(1) or "text"
        code = match.group(2)
        # Normalize common aliases
        lang_map = {"py": "python", "js": "javascript", "ts": "typescript",
                    "sh": "bash", "yml": "yaml", "rb": "ruby", "rs": "rust"}
        lang = lang_map.get(lang, lang)
        syntax = Syntax(code, lang, theme="monokai", line_numbers=False,
                        word_wrap=True, background_color="default")
        parts.append(Panel(syntax, border_style="dim cyan", padding=(1, 2)))

        last_end = match.end()

    # Text after the last code block
    after = text[last_end:]
    if after.strip():
        parts.append(Markdown(after, code_theme="monokai"))

    from rich.group import Group
    return Group(*parts) if parts else Markdown(text, code_theme="monokai")


def render_diff(diff_text: str) -> Panel:
    """Render a unified diff with line numbers and syntax coloring."""
    return Panel(
        Syntax(diff_text, "diff", theme="monokai", line_numbers=True,
               word_wrap=True, background_color="default"),
        title="Diff", border_style="cyan", padding=(1, 2)
    )


def render_thinking_block(reasoning: str) -> Panel:
    """Render a thinking/reasoning block in a collapsible-style panel."""
    preview = reasoning[:500].replace("\n", "\n  ")
    if len(reasoning) > 500:
        preview += f"\n  [dim]... ({len(reasoning)} chars total)[/dim]"
    return Panel(
        Markdown(preview, code_theme="monokai"),
        title="💭 Thinking", border_style="dim magenta", padding=(0, 2)
    )


def render_error_block(error_msg: str, suggestion: str = "") -> Panel:
    """Render an error with optional suggestion."""
    content = Text(error_msg, style="red")
    if suggestion:
        content += Text(f"\n\n💡 {suggestion}", style="dim yellow")
    return Panel(content, title="✗ Error", border_style="red", padding=(1, 2))


def show_tool_progress(name: str, args: dict, status: str = "running"):
    """Show a tool execution with spinner animation.

    Args:
        name: Tool name
        args: Tool arguments (preview only)
        status: 'running' or 'done'
    """
    short = json.dumps(args, ensure_ascii=False)
    if len(short) > 50:
        short = short[:47] + "..."

    if status == "running":
        console.print(f"[bold yellow]●[/bold yellow] [cyan]{name}[/cyan] [dim]{short}[/dim]")
    else:
        console.print(f"[bold green]✓[/bold green] [cyan]{name}[/cyan] [dim]{short}[/dim]")


def show_turn_summary(turn: int, input_tokens: int,
                      output_tokens: int, elapsed: str = "",
                      balance: str = ""):
    """Single-line turn summary like Claude Code / DeepCode."""
    parts = [
        f"[bold dim]Turn {turn}[/bold dim]",
        f"[dim]{input_tokens:,}t in[/dim]",
        f"[dim]{output_tokens:,}t out[/dim]",
        f"[dim]{elapsed}[/dim]",
    ]
    if balance:
        parts.append(f"[dim]💰 {balance}[/dim]")
    console.print("  " + "  ·  ".join(parts))



# Legacy compatibility — show_diff still used by session_stream
def show_diff(diff_text: str):
    """Display diff with line-by-line coloring (backward compat)."""
    lines = diff_text.split("\n")
    for line in lines[:30]:
        if line.startswith("+"):
            console.print(f"[green]  + {line[1:]}[/green]")
        elif line.startswith("-"):
            console.print(f"[red]  - {line[1:]}[/red]")
        elif line.startswith("@@"):
            console.print(f"[cyan]  {line}[/cyan]")
        else:
            console.print(f"[dim]  {line}[/dim]")
    if len(lines) > 30:
        console.print(f"[dim]  ... ({len(lines) - 30} more lines)[/dim]")
