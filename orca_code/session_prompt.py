"""orca_code.session_prompt — System prompt construction.

Extracted from session.py. Supports both inline (legacy) and template-based
prompt construction via infrastructure/prompt_loader.
"""

from __future__ import annotations

import getpass
import json
import logging
import platform as _platform
from datetime import datetime

from orca_code.config import (
    BASE_URL,
    CONTEXT_MAX_TOKENS,
    HAS_MEMORY,
    IS_DEEPSEEK,
    IS_LOCAL,
    IS_MULTIMODAL,
    MAX_OUTPUT_TOKENS,
    MODEL,
    PERSONA,
    REASONING_EFFORT,
    USE_SIMPLE_PROMPT,
    WORKING_DIR,
    mem_mgr,
)
from orca_code.constitution import get_constitution, inject_constitution
from orca_code.tool_registry import TOOLS
from orca_code.utils import _estimate_tokens

# Optional: template-based prompt loading (new system)
try:
    from orca_code.infrastructure.prompt_loader import load_prompt
    _HAS_TEMPLATES = True
except ImportError:
    _HAS_TEMPLATES = False


def build_system_prompt() -> str:
    # ---- Simple prompt for Gemma / Qwen / Ministral ----
    if USE_SIMPLE_PROMPT:
        prompt = (
            "你是智能桌面助手，用中文回复。\n\n"
            "核心原则：\n"
            "- 直接行动，不问。用户发路径就 list_files。\n"
            "- 工具返回后，判断下一步逻辑并立即执行，不要停下来问用户'你想做什么'。\n"
            "- 有多个文件时全部读取，不要只读一个。\n"
            "- 用一句话总结工具结果，然后直接做下一步。\n"
            "- 不要预告。你说'我来读取'就是在浪费token——直接调工具。\n\n"
            "操作优先级: CLI > API > GUI\n"
            "- 能用 execute_command 完成的不要用 GUI 工具\n"
            "- 启动应用用 Start-Process，不要模拟按键\n"
            "- GUI 工具仅在无 CLI 替代方案时使用\n\n"
            "文件规则：\n"
            "- .doc/.docx → read_word, .xls/.xlsx → read_excel\n"
            "- .txt/.py/.json/.md 等 → read_file\n"
            "- 输出一律写到 output/ 目录\n\n"
            "行为准则：\n"
            "- 工具报错时排查根因并修复，不要直接放弃\n"
            "- 写代码简洁务实，不写注释，不做过度抽象\n"
            "- 查天气前先调 get_location\n"
            "- web_search 后用 read_webpage 读取结果页面\n"
            "- 只在用户明确要求时使用 GUI/浏览器自动化\n"
        )
        if IS_MULTIMODAL:
            prompt += "\n你可以直接查看图片，无需调用 analyze_image。"
        if PERSONA:
            prompt += f"\n\n[用户偏好]\n{PERSONA}"
        return inject_constitution(prompt)

    # ---- Full prompt for DeepSeek and other capable models ----
    prompt = (
        "You are a desktop AI assistant. Always reply in Chinese (中文).\n\n"
        "OPERATIONS PRIORITY: CLI > API > GUI\n"
        "- Prefer execute_command (PowerShell/cmd) for all tasks that have a command-line path.\n"
        "- Use GUI tools (gui_click, gui_type, window_focus, find_on_screen) ONLY when no CLI alternative exists (e.g. UWP apps, GUI-only software).\n"
        "- For app launching: Start-Process, not Win+R simulation.\n"
        "- For file operations: use shell commands, not GUI file manager navigation.\n\n"
        "CRITICAL RULES:\n"
        "- Root-cause errors — use read_file/search_content to inspect the failing target; fix, don't just report.\n"
        "- Past failures do NOT mean a tool is permanently broken — retry the correct approach first.\n"
        "- Call update_profile whenever you learn user preferences, projects, tools, coding style, or answer format.\n"
        "- After creating/launching, just report success — don't screenshot-verify what the user can already see.\n"
        "- Each reply: 3 sentences max. No filler ('好的', '让我', '我来'). State result directly.\n"
        "- Never repeat the user's message back to them.\n"
        "- Every tool call must change your next action — skip calls that add no new information.\n\n"
        "Standard Rules:\n"
        "- Explore with tools before guessing.\n"
        "- Write clean, pragmatic code — no comments, no over-abstraction.\n"
        "- Call get_location before get_weather.\n"
        "- web_search → then read_webpage to get full content from results.\n"
        "- File output always to output/ relative path.\n"
        "- Manage skills via load_skill/create_skill/edit_skill/list_skills and load_md_skill/list_md_skills.\n"
        "- Manage tasks via add_task/list_tasks/remove_task.\n"
        "- Only use GUI/browser automation when explicitly asked or when CLI path is exhausted.\n"
    )
    if IS_MULTIMODAL:
        prompt += (
            "\nYou CAN see images directly. Do NOT call analyze_image or capture_camera "
            "for images the user sends — just look at them. Use analyze_image only as fallback."
        )
    # Model identity
    prompt += (
        f"\n\nRunning as: {MODEL} | Base URL: {BASE_URL} | "
        f"Local: {IS_LOCAL} | Multimodal: {IS_MULTIMODAL}."
    )
    prompt += (
        "\nYou have a long-term memory system. When the user asks about past discussions, "
        "use recall_conversation to search in the USER'S LANGUAGE. "
        "Try broad queries first, then narrow. If no results, try a different query before giving up."
    )

    # User profile
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
            "BUILD THE PROFILE AGGRESSIVELY. Every time you learn something about the user — "
            "preferences, projects, tools, coding style, answer format — call update_profile. "
            "If profile is empty and you observe ANY facts, populate it NOW. Profile persists across sessions."
        )
    # Inject Constitution as the highest-authority prefix (cached by DeepSeek KV cache)
    return inject_constitution(prompt)
_CACHED_PREFIX_TOKENS = None
def _estimate_prefix_tokens() -> int:
    global _CACHED_PREFIX_TOKENS
    if _CACHED_PREFIX_TOKENS is None:
        text = build_system_prompt() + json.dumps(TOOLS, ensure_ascii=False)
        _CACHED_PREFIX_TOKENS = _estimate_tokens(text)
    return _CACHED_PREFIX_TOKENS


# ═══════════════════════════════════════════════════════════════════════════════
# Template-based prompt builder (v2)
# Uses orca_code/prompts/*.md templates when available.
# ═══════════════════════════════════════════════════════════════════════════════

def _get_template_vars() -> dict:
    """Build the common template variable dict."""
    profile = PERSONA or ""
    if HAS_MEMORY and mem_mgr:
        try:
            learned = mem_mgr.get_meta("user_profile")
            if learned:
                if profile:
                    profile += "\n" + learned
                else:
                    profile = learned
        except Exception:
            pass

    return {
        "constitution": get_constitution(),
        "platform": _platform.system(),
        "platform_release": _platform.release(),
        "username": getpass.getuser(),
        "working_dir": str(WORKING_DIR),
        "current_date": datetime.now().strftime("%Y-%m-%d %A"),
        "tool_count": str(len(TOOLS)),
        "persona": profile if profile else "(none)",
        "user_profile": "",
        "model": MODEL,
        "base_url": BASE_URL,
        "is_multimodal": str(IS_MULTIMODAL).lower(),
        "max_output_tokens": str(MAX_OUTPUT_TOKENS),
        "context_max_tokens": str(CONTEXT_MAX_TOKENS),
        "reasoning_effort": REASONING_EFFORT,
        "high": REASONING_EFFORT == "high",
        "medium": REASONING_EFFORT == "medium",
    }


def build_system_prompt_v2() -> str | None:
    """Build system prompt from templates. Returns None if templates unavailable.

    Uses template-based prompts from orca_code/prompts/ instead of inline strings.
    The template system supports per-model variants and variable substitution.
    """
    if not _HAS_TEMPLATES:
        return None

    try:
        vars_dict = _get_template_vars()

        # Select template based on model type
        if USE_SIMPLE_PROMPT:
            template_name = "system/simple"
        elif IS_DEEPSEEK:
            template_name = "system/deepseek"
        else:
            template_name = "system/base"

        prompt = load_prompt(template_name, **vars_dict)

        # Inject model identity line
        prompt += (
            f"\n\nRunning as: {MODEL} | Base URL: {BASE_URL} | "
            f"Local: {IS_LOCAL} | Multimodal: {IS_MULTIMODAL}."
        )

        # Inject Constitution as cached prefix
        return inject_constitution(prompt)

    except Exception as e:
        logging.debug("Template prompt loading failed: %s, falling back to inline", e)
        return None
