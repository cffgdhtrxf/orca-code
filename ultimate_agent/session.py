"""ultimate_agent.session — Session, system prompt, UI, messages, API."""

import os, sys, json, re, time, logging, inspect
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import openai
from openai import OpenAI
import tenacity
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from ultimate_agent.config import (CONFIG, MODEL, BASE_URL, API_KEY,
    IS_DEEPSEEK, IS_LOCAL, IS_MULTIMODAL, USE_SIMPLE_PROMPT,
    ENABLE_THINK_MODE, REASONING_EFFORT, MAX_OUTPUT_TOKENS,
    CONTEXT_MAX_TOKENS, KEEP_ROUNDS, PERSONA, HAS_MEMORY, HAS_TTS,
    ENABLE_TTS, ENABLE_GUI_AUTO, ENABLE_BROWSER_AUTO, VISION_MODEL,
    TERM_WIDTH, SAVE_DIR, WORKING_DIR, MAX_WORKERS, mem_mgr, client, console, mask_key)
from ultimate_agent.utils import (_sanitize_ansi, _strip_html, _estimate_tokens,
    _sanitize_for_save, fix_truncated_json)
from ultimate_agent.tools_core import get_system_info

# Lazy import: TOOLS/TOOL_MAP live in main.py (imported after session), resolve at runtime
def _get_tools():
    from ultimate_agent.main import TOOLS
    return TOOLS

def _get_tool_map():
    from ultimate_agent.main import TOOL_MAP
    return TOOL_MAP

def sanitize_messages(messages: list) -> list:
    valid_tool_ids: set = set()
    for msg in messages:
        if msg.get('role') == 'assistant' and msg.get('tool_calls'):
            for tc in msg['tool_calls']:
                tc_id = tc.get('id', '')
                if tc_id:
                    valid_tool_ids.add(tc_id)
    cleaned = []
    for msg in messages:
        if msg.get('role') == 'tool':
            if msg.get('tool_call_id', '') not in valid_tool_ids:
                continue
        cleaned.append(msg)
    result_tool_ids = {m.get('tool_call_id') for m in cleaned if m.get('role') == 'tool'}
    for msg in cleaned:
        if msg.get('role') == 'assistant' and msg.get('tool_calls'):
            msg['tool_calls'] = [tc for tc in msg['tool_calls']
                                  if tc.get('id') in result_tool_ids]
            # DeepSeek API rejects empty tool_calls array — remove the key if empty
            if not msg['tool_calls']:
                del msg['tool_calls']
    # [D12] Adjacency sanitization: remove tool messages without assistant/tool predecessor
    final = []
    for msg in cleaned:
        if msg.get("role") == "tool":
            if not final or final[-1].get("role") not in ("assistant", "tool"):
                continue
        final.append(msg)
    return final
def _msg_tokens(msg: dict) -> int:
    """Estimate token count for a message. Base64 images counted as ~200 tokens."""
    raw = json.dumps(msg, ensure_ascii=False)
    has_image = 'data:image/' in raw
    clean = re.sub(r'data:image/\w+;base64,[A-Za-z0-9+/=]{500,}', '', raw)
    tokens = _estimate_tokens(clean)
    if has_image:
        tokens += 200  # multimodal models count each image as ~85-200 tokens
    return tokens
def _extract_text(msg: dict) -> str:
    """Extract plain text from a message (handles multimodal content arrays)."""
    content = msg.get("content", "")
    if isinstance(content, list):
        parts = [p.get("text","") for p in content if isinstance(p, dict) and p.get("type")=="text"]
        return " ".join(parts)
    return str(content) if content else ""
def _llm_compress_blocks(blocks: list, llm_client=None, llm_model: str = "") -> list:
    """Compress old conversation blocks into a single summary using LLM.
    Level 1=LLM, Level 2=rule-based, Level 3=empty (skip compression)."""
    if not blocks:
        return []

    turns_text = []
    for block in blocks:
        user_text = ""
        assistant_text = ""
        for m in block:
            text = _extract_text(m)
            if m.get("role") == "user" and text:
                user_text = text[:300]
            elif m.get("role") == "assistant" and text:
                assistant_text = text[:300]
        if user_text:
            turns_text.append(f"[user]: {user_text}")
            if assistant_text:
                turns_text.append(f"[assistant]: {assistant_text}")

    if not turns_text:
        return []

    conversation_text = "\n".join(turns_text)

    # Level 1: LLM compression
    if llm_client and llm_model:
        try:
            prompt = (
                "Compress the following conversation into a single paragraph (~200 chars, "
                "same language as user). Keep: key decisions, requests answered, code written, "
                "files created, preferences, unresolved issues. Omit greetings and small talk.\n\n"
                f"{conversation_text}\n\nSummary:"
            )
            resp = llm_client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "system", "content": "Output ONLY the summary paragraph."},
                          {"role": "user", "content": prompt}],
                max_tokens=300, temperature=0.3,
            )
            summary = (resp.choices[0].message.content or "").strip()[:400]
            if summary:
                return [
                    {"role": "user", "content": f"[Previous conversation summary]: {summary}"},
                    {"role": "assistant", "content": "Got it, I have the context."}
                ]
        except Exception as e:
            logging.debug("LLM compression failed: %s", e)

    # Level 2: Rule-based fallback — concat first 150 chars of each user message
    lines = []
    for block in blocks:
        for m in block:
            if m.get("role") == "user":
                text = _extract_text(m)[:150].replace('\n', ' ')
                if text:
                    lines.append(text)
    if lines:
        summary = "；".join(lines[:10])
        return [
            {"role": "user", "content": f"[Previous conversation summary]: {summary}"},
            {"role": "assistant", "content": "Got it, I have the context."}
        ]

    # Level 3: Nothing to compress
    return []
def smart_trim_messages(messages: list, max_tokens: int = None,
                        llm_client=None, llm_model: str = "") -> list:
    if max_tokens is None:
        max_tokens = CONTEXT_MAX_TOKENS
    total_tokens = sum(_msg_tokens(m) for m in messages)
    trigger = int(max_tokens * 0.75)
    target = int(max_tokens * 0.55)
    if total_tokens <= trigger:
        return messages

    # Find system message (may not always be at index 0)
    system_msg = None
    sys_idx = -1
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            system_msg = m
            sys_idx = i
            break
    if system_msg is None:
        # [FIX] Fallback: keep last N messages to prevent context overflow
        keep = max(20, len(messages) // 2)
        return messages[-keep:]
    rest = messages[sys_idx + 1:]

    # Remove existing summary pair if present (will be regenerated)
    summary_prefix = "[Previous conversation summary]:"
    if (rest and rest[0].get("role") == "user" and
            isinstance(rest[0].get("content", ""), str) and
            rest[0]["content"].startswith(summary_prefix)):
        rest = rest[2:] if len(rest) > 1 and rest[1].get("role") == "assistant" else rest[1:]

    # Split into conversation blocks
    blocks = []
    i = 0
    while i < len(rest):
        msg = rest[i]
        if msg.get('role') == 'user':
            block = [msg]
            i += 1
            while i < len(rest) and rest[i].get('role') in ('assistant', 'tool'):
                block.append(rest[i])
                i += 1
            blocks.append(block)
        elif msg.get('role') == 'assistant':
            block = [msg]
            i += 1
            while i < len(rest) and rest[i].get('role') == 'tool':
                block.append(rest[i])
                i += 1
            blocks.append(block)
        else:
            blocks.append([msg])
            i += 1

    if len(blocks) <= KEEP_ROUNDS:
        return messages

    # Compress: keep last KEEP_ROUNDS, compress the rest
    keep = min(KEEP_ROUNDS, len(blocks) - 1)
    to_compress = blocks[:-keep]
    recent = blocks[-keep:]

    # Build time range for compressed messages
    ts_start = ts_end = ""
    for m in (to_compress[0] if to_compress else []):
        if isinstance(m.get("content"), str):
            ts_start = datetime.now().strftime("%Y-%m-%d %H:%M")
            break
    ts_end = datetime.now().strftime("%Y-%m-%d %H:%M")
    time_range = f"{ts_start} ~ {ts_end}"

    compressed = _llm_compress_blocks(to_compress, llm_client, llm_model) if to_compress else []
    result = [system_msg] + compressed + [m for b in recent for m in b]

    # Dynamic reduction: if still over target, reduce keep rounds
    result_tokens = sum(_msg_tokens(m) for m in result)
    rounds = keep
    while result_tokens > target and rounds > 5:
        rounds = max(5, rounds - 5)
        to_compress2 = blocks[:-rounds]
        recent2 = blocks[-rounds:]
        compressed2 = _llm_compress_blocks(to_compress2, llm_client, llm_model) if llm_client else compressed
        result = [system_msg] + (compressed2 or compressed) + [m for b in recent2 for m in b]
        result_tokens = sum(_msg_tokens(m) for m in result)

    # Persist summary to DB for cross-session
    if compressed and HAS_MEMORY and mem_mgr:
        try:
            summary_text = _extract_text(compressed[0])
            if summary_text.startswith(summary_prefix):
                mem_mgr.set_meta("rolling_summary", summary_text[len(summary_prefix):].strip())
                mem_mgr.set_meta("rolling_summary_range", time_range)
        except Exception:
            pass

    before = sum(_msg_tokens(m) for m in messages)
    after = sum(_msg_tokens(m) for m in result)
    if len(result) < len(messages):
        console.print(f'[dim][压缩] {len(messages)}条 → {len(result)}条 | {before}→{after} tokens (省{before-after})[/dim]')
    return result
class Session:
    def __init__(self):
        self.turns: int = 0
        self.tool_calls: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cached_tokens: int = 0
        self.total_reasoning_tokens: int = 0
        self.start_time: float = time.time()
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
        t = time.time() - self.start_time
        if t < 60:
            return f'{t:.0f}秒'
        elif t < 3600:
            return f'{t / 60:.0f}分{t % 60:.0f}秒'
        else:
            return f'{t / 3600:.0f}时{(t % 3600) / 60:.0f}分'
session = Session()
def build_system_prompt() -> str:
    # ---- Simple prompt for Gemma / Qwen / Ministral ----
    # These smaller models perform better with concise, non-contradictory instructions
    if USE_SIMPLE_PROMPT:
        prompt = (
            "你是智能桌面助手，用中文回复。\n\n"
            "核心原则：\n"
            "- 直接行动，不问。用户发路径就 list_files。\n"
            "- 工具返回后，判断下一步逻辑并立即执行，不要停下来问用户'你想做什么'。\n"
            "- 有多个文件时全部读取，不要只读一个。需要完整信息才能准确回答。\n"
            "- 用一句话总结工具结果，然后直接做下一步。\n"
            "- 不要预告。你说'我来读取'就是在浪费token——直接调工具。说'下一步我将'而不调工具就是撒谎。\n\n"
            "文件读取规则：\n"
            "- .doc/.docx → read_word\n"
            "- .xls/.xlsx → read_excel\n"
            "- .txt/.py/.json/.md 等纯文本 → read_file\n\n"
            "行为准则：\n"
            "- 看屏幕布局/窗口/GUI状态：用 analyze_image（视觉模型能看到图标、窗口、按钮位置）\n"
            "- 提取纯文本/代码/终端输出：用 ocr_image（本地OCR，快且准确）\n"
            "- 同一张截图只用一个工具，截图→分析一步到位，不要截图后ocr再analyze\n"
            "- 工具报错时排查根因并修复，不要直接放弃\n"
            "- 写代码简洁务实，不写注释，不做过度抽象\n"
            "- 查天气前先调用 get_location 获取城市名\n"
            "- 用 web_search 搜索后，用 read_webpage 读取结果页面获取完整内容\n"
            "- 只在用户明确要求时使用 GUI/浏览器自动化\n"
            "- 文件输出一律用相对路径写到 output/ 目录（如 output/result.png），不要写桌面或绝对路径\n"
            "- 启动软件 / 运行命令 / 查注册表 / 操作文件 → 一律优先用 execute_command + PowerShell\n"
            "- 启动软件: Start-Process '路径'（1步完成），不要用 Win+R 模拟按键绕路\n"
            "- 找不到 exe: Get-ItemProperty HKLM:\\...\\App Paths\\ 查注册表，不要全盘 search_files\n"
            "- 操作桌面应用: window_focus 激活 → gui_click 点输入框 → gui_type 粘贴 → gui_press('enter') 发送\n"
            "- 发消息不要像素验证！gui_press('enter') 后直接告诉用户已发送，输入框残留UI元素不算文字\n"
            "- find_on_screen 返回带坐标的文字列表，直接 gui_click 点坐标，不要自己写 execute_python 扫描像素\n"
            "- PowerShell 搞不定再用 gui_hotkey / gui_type 兜底\n"
        )
        if IS_MULTIMODAL:
            prompt += (
                "\n你可以直接查看图片。用户发送照片或截图时直接分析，"
                "无需调用 analyze_image 或 capture_camera。"
            )
        if PERSONA:
            prompt += f"\n\n[用户偏好]\n{PERSONA}"
        return prompt

    # ---- Full prompt for DeepSeek and other capable models ----
    prompt = (
        "You are a desktop AI assistant that operates the computer.\n"
        "Always reply in Chinese (中文). Use the same language as the user.\n\n"
        "CRITICAL RULES:\n"
        "- When a tool returns an error, dig into the ROOT CAUSE first — use read_file, search_content, or execute_python to inspect the failing script/config. Fix the problem; don't just report failure\n"
        "- Past failures in conversation history do NOT mean a tool is permanently broken — conditions may have changed (user enabled location, installed a package, etc.). Always try the correct tool first before falling back\n"
        "- If a tool fails in THIS turn, try to debug the root cause. Only switch approach if you confirm the tool is genuinely unavailable RIGHT NOW\n"
        "- Call update_profile whenever you learn anything about the user: location, language preference, projects, tools, coding style, answer format preference. Check the profile at session start — if empty, fill it from what you observe\n"
        "- execute_command, execute_python, subprocess, os.system, ctypes, file writes are BLOCKED by sandbox — do NOT try them\n"
        "- After launching an app or creating a file, just tell the user — do NOT screenshot-verify what the user can already see\n"
        "- Each reply: 3 sentences max. Cut all filler ('好的', '让我', '我来'). Skip process narration. State result directly\n"
        "- Never repeat what the user just said\n"
        "- Every tool call must change your next action. If it won't, skip it\n\n"
        "Standard Rules:\n"
        "- Explore with tools before guessing\n"
        "- Write clean, pragmatic code — no comments, no over-abstraction\n"
        "- Call get_location before get_weather\n"
        "- Manage skills via load_skill/create_skill/edit_skill/list_skills (for .py tools) and load_md_skill/list_md_skills (for .md behavioral protocols)\n"
        "- Manage tasks via add_task/list_tasks/remove_task\n"
        "- Only use GUI/browser automation when explicitly asked\n"
    )
    if IS_MULTIMODAL:
        prompt += (
            "\nYou CAN see images directly. When the user sends a photo or screenshot, "
            "just look at it and reply — do NOT call analyze_image or capture_camera. "
            "Only use analyze_image as a fallback if you truly cannot see the image."
        )
    # Model identity
    prompt += (
        f"\n\nYou are running as model: {MODEL}. "
        f"Base URL: {BASE_URL}. Local: {IS_LOCAL}. Multimodal: {IS_MULTIMODAL}."
    )
    prompt += (
        "\nYou have a long-term memory system. When the user asks about past discussions, "
        "use recall_conversation to search. Search in the USER'S LANGUAGE (Chinese=中文关键词, English=English keywords). "
        "Try broad queries first ('聊天', 'discussion'), then narrow down.\n"
        "When results come back: summarize TOPICS ('we discussed weather, a CSV script'). "
        "If no results, try a different query before giving up. Never say 'no history found' on the first try."
    )

    # User profile: seed persona + learned traits from meta
    profile_parts = []
    if PERSONA:
        profile_parts.append(PERSONA)
    if HAS_MEMORY and mem_mgr:
        try:
            learned = mem_mgr.get_meta("user_profile")
            if learned:
                profile_parts.append(learned)
        except Exception as e:
            logging.debug("profile read error: %s", e)
    if profile_parts:
        prompt += (
            f"\n\n[USER PROFILE]\n{' '.join(profile_parts)}\n\n"
            "BUILD THE PROFILE AGGRESSIVELY. Every time the user mentions a preference, "
            "a project they work on, a tool they use, their location, their coding style, "
            "or how they want answers — call update_profile IMMEDIATELY. "
            "If the profile is empty and you can see ANY facts about the user from this conversation, "
            "populate it NOW. The profile persists across sessions."
        )
    return prompt
_CACHED_PREFIX_TOKENS = None
def _estimate_prefix_tokens() -> int:
    global _CACHED_PREFIX_TOKENS
    if _CACHED_PREFIX_TOKENS is None:
        text = build_system_prompt() + json.dumps(_get_tools(), ensure_ascii=False)
        _CACHED_PREFIX_TOKENS = _estimate_tokens(text)
    return _CACHED_PREFIX_TOKENS
def print_gap() -> None:
    console.print()
    console.print(f"[dim]{'─' * min(TERM_WIDTH, 80)}[/dim]")
    console.print()
def print_soft_gap() -> None:
    console.print()
def show_tool_call(name: str, args: dict) -> None:
    short = json.dumps(args, ensure_ascii=False)
    if len(short) > 55:
        short = short[:52] + '...'
    console.print(f"[bold green]●[/bold green] [#F9F1A5]{name}[/#F9F1A5] [dim]{short}[/dim]")
def show_tool_result(result, tool_name=""):
    if tool_name in ("web_fetch", "read_webpage") and result.startswith("<!DOCTYPE"):
        result = _strip_html(result)
    lines = result.split("\n")
    max_show = len(lines) if tool_name == "get_weather" else 12
    for line in lines[:max_show]:
        if len(line) > TERM_WIDTH:
            line = line[:TERM_WIDTH - 3] + "..."
        console.print(f"[dim]  | {line}[/dim]")
    if len(lines) > max_show:
        console.print(f"[dim]  | ... 共 {len(lines)} 行，已截断[/dim]")
def show_tool_done(elapsed_ms, parallel=False):
    suffix = " (并行)" if parallel else ""
    console.print(f"[dim]  └── {elapsed_ms:.0f}ms{suffix}[/dim]")
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
    console.print(f"[dim]模式: {mode_str}  |  模型: {MODEL}  |  视觉: {vision_str}[/dim]")
    console.print(f"[dim]思考: {'on' if ENABLE_THINK_MODE else 'off'}  |  "
                  f"工具: {len(_get_tools())}个  |  GUI: {gui_status}  |  浏览器: {browser_status}[/dim]")
    if not IS_LOCAL:
        console.print(f"[dim]API Key: {mask_key(API_KEY)}[/dim]")
    console.print(f"[dim]工作目录: {WORKING_DIR}[/dim]")
    console.print(f"[dim]/help 帮助  |  /clear 清空  |  /stats 统计  |  /save 导出  |  exit 退出[/dim]")
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
    console.print("  exit     退出程序")
    console.print()
    console.print("[bold]可用工具[/bold]")
    for name in _get_tool_map():
        console.print(f"  {name}")
def show_stats():
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
            console.print(f"[green]已导出: {export_path}[/green]")
            return str(export_path)
        except Exception as e:
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
def call_model(messages):
    # Prepare messages for API
    api_messages = []
    for m in messages:
        clean = dict(m)
        role = clean.get("role", "")
        # reasoning_content handling per DeepSeek spec:
        # - Tool-call turns: MUST preserve (API requires it for thinking mode)
        # - Non-tool-call turns: can strip (API ignores it, saves tokens)
        # - Non-DeepSeek/Local: always strip (other APIs may reject it)
        if not IS_DEEPSEEK or IS_LOCAL:
            clean.pop("reasoning_content", None)
        elif role == "assistant" and not clean.get("tool_calls"):
            clean.pop("reasoning_content", None)  # harmless to strip, saves tokens
        # else: tool_calls present → preserve reasoning_content per DeepSeek spec

        # Fix null content (some APIs reject None)
        if role == "assistant" and clean.get("content") is None:
            clean["content"] = ""
        # DeepSeek API rejects empty tool_calls array — remove it
        if role == "assistant" and isinstance(clean.get("tool_calls"), list):
            if not clean["tool_calls"]:
                del clean["tool_calls"]
        # Strip multimodal image content for non-multimodal models
        if not IS_MULTIMODAL and isinstance(clean.get("content"), list):
            texts = [p.get("text","") for p in clean["content"] if isinstance(p, dict) and p.get("type")=="text"]
            clean["content"] = " ".join(texts) if texts else "[image]"
        api_messages.append(clean)

    kwargs = {
        "model": MODEL,
        "messages": api_messages,
        "tools": _get_tools(),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    # max_tokens: skip for Gemma/simple-mode models (let the server decide)
    if not USE_SIMPLE_PROMPT:
        kwargs["max_tokens"] = MAX_OUTPUT_TOKENS
    # DeepSeek-specific: thinking + reasoning_effort
    if IS_DEEPSEEK and not IS_LOCAL:
        if ENABLE_THINK_MODE:
            kwargs["reasoning_effort"] = REASONING_EFFORT
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            # Disable temperature for thinking mode (spec requirement)
            kwargs.pop("temperature", None)
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    # [A1] Tenacity retry with exponential backoff (3 attempts, 2s-10s)
    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        retry=tenacity.retry_if_exception_type((
            openai.APIConnectionError, openai.APITimeoutError,
            openai.RateLimitError, openai.InternalServerError
        )),
        before_sleep=lambda rs: console.print(
            f"[yellow]API 网络/限流异常，{rs.next_action.sleep:.1f}秒后重试 ({rs.attempt_number}/3)...[/yellow]"
        )
    )
    def _create_with_retry(_kwargs):
        return client.chat.completions.create(**_kwargs)

    return _create_with_retry(kwargs)
def process_stream(stream):
    reasoning_full = ""
    answer_full = ""
    tool_calls_by_index = {}
    usage = None
    thinking_started = False
    t_answer_start = None
    answer_status = None

    for chunk in stream:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = chunk.usage
            continue

        delta = chunk.choices[0].delta

        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            if not thinking_started:
                console.print()
                # [F18] ANSI italic dim for thinking display
                sys.stdout.write("\033[2;90;3m💭 ")
                sys.stdout.flush()
                thinking_started = True
            display = _sanitize_ansi(delta.reasoning_content.replace("\n", "\n  "))
            sys.stdout.write(display)
            sys.stdout.flush()
            reasoning_full += delta.reasoning_content

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_by_index:
                    tool_calls_by_index[idx] = {
                        "id": "", "function_name": "", "function_arguments": ""
                    }
                entry = tool_calls_by_index[idx]
                if tc.id:
                    entry["id"] = tc.id
                if tc.function and tc.function.name:
                    entry["function_name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    entry["function_arguments"] += tc.function.arguments

        if delta.content:
            if t_answer_start is None:
                t_answer_start = time.time()
                if thinking_started:
                    console.print()
                answer_status = console.status(
                    "[dim]生成中... 0 字[/dim]",
                    spinner="dots", spinner_style="bright_black",
                )
                answer_status.start()
            answer_full += delta.content
            elapsed = time.time() - t_answer_start
            label = f"[dim]生成中... {len(answer_full)} 字"
            if elapsed >= 1:
                label += f" · {elapsed:.0f}s"
            answer_status.update(label + "[/dim]")

    if reasoning_full:
        session.last_thinking = reasoning_full

    # [F18] Reset ANSI after thinking
    if thinking_started:
        sys.stdout.write("\033[0m\n")
        sys.stdout.flush()

    if answer_status is not None:
        answer_status.stop()

    if answer_full:
        console.print("[bold white]●[/bold white] ", end="")
        md = Markdown(answer_full, code_theme="monokai")
        console.print(Padding(md, (0, 0, 0, 2)))
    else:
        console.print()

    return reasoning_full, answer_full, tool_calls_by_index, usage
def execute_tool_calls(tool_calls_by_index):
    from ultimate_agent.main import run_tool
    items = []
    for idx in sorted(tool_calls_by_index.keys()):
        tc = tool_calls_by_index[idx]
        fn_name = tc["function_name"]
        raw_args = tc["function_arguments"]

        if raw_args:
            fixed_args, was_fixed = fix_truncated_json(raw_args)
            if was_fixed:
                console.print(f"[yellow]⚠ {fn_name} 参数 JSON 已截断，已自动修复[/yellow]")
            try:
                fn_args = json.loads(fixed_args)
            except json.JSONDecodeError:
                fn_args = {}
                console.print(f"[red]✗ {fn_name} 参数 JSON 修复失败，使用空参数[/red]")
        else:
            fn_args = {}

        show_tool_call(fn_name, fn_args)
        items.append((idx, tc, fn_name, fn_args))

    if len(items) == 1:
        idx, tc, fn_name, fn_args = items[0]
        t0 = time.time()
        result = run_tool(fn_name, fn_args)
        elapsed = (time.time() - t0) * 1000
        show_tool_result(result, fn_name)
        show_tool_done(elapsed)
        session.tool_calls += 1
        return (
            [{"id": tc["id"], "type": "function",
              "function": {"name": fn_name, "arguments": tc["function_arguments"]}}],
            [{"role": "tool", "tool_call_id": tc["id"] or f"call_{idx}", "content": result}]
        )

    items_by_idx = {idx: (fn, args) for idx, tc, fn, args in items}
    results_map = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(items))) as ex:
        future_to_idx = {}
        for idx, (fn, args) in items_by_idx.items():
            future_to_idx[ex.submit(run_tool, fn, args)] = idx
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results_map[idx] = future.result()
            except Exception as e:
                results_map[idx] = f"错误: {e}"

    elapsed = (time.time() - t0) * 1000
    tool_calls = []
    tool_results = []
    for idx, tc, fn_name, fn_args in items:
        result = results_map.get(idx, "错误: 未获取到结果")
        show_tool_result(result, fn_name)
        session.tool_calls += 1
        tool_calls.append({
            "id": tc["id"], "type": "function",
            "function": {"name": fn_name, "arguments": tc["function_arguments"]}
        })
        tool_results.append({
            "role": "tool", "tool_call_id": tc["id"] or f"call_{idx}", "content": result
        })
    show_tool_done(elapsed, parallel=True)
    return tool_calls, tool_results