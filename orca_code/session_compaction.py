"""orca_code.session_compaction — Context window compaction (P1-7).

Primary: headroom-ai (SmartCrusher, CodeCompressor, LogCompressor, etc.)
Fallback: rule-based turn truncation.

When headroom is installed (pip install -e .[compression]), compaction uses
headroom's 6-algorithm pipeline. When not installed, falls back to the
original rule-based strategy.
"""

from __future__ import annotations

from orca_code.config import CONTEXT_MAX_TOKENS, KEEP_ROUNDS
from orca_code.session_messages import _msg_tokens

# ─── Headroom (optional — auto-installed if AUTO_INSTALL_DEPS is true) ──────
# headroom-ai 提供 6 种上下文压缩算法，安装后可节省 60-95% token。
# 自动安装：设置 config.json 中 auto_install_deps: true，首次使用时自动 pip install。
# 手动安装：pip install -e ".[compression]"
try:
    from headroom import compress as _headroom_compress
    from headroom import CompressConfig as _HeadroomConfig
    HAS_HEADROOM = True
except ImportError:
    from orca_code.config import AUTO_INSTALL_DEPS
    if AUTO_INSTALL_DEPS:
        from orca_code.infrastructure.helpers import ensure_pkg
        if ensure_pkg("headroom-ai", "headroom"):
            try:
                from headroom import compress as _headroom_compress
                from headroom import CompressConfig as _HeadroomConfig
                HAS_HEADROOM = True
            except ImportError:
                HAS_HEADROOM = False
        else:
            HAS_HEADROOM = False
    else:
        HAS_HEADROOM = False
    if not HAS_HEADROOM:
        _headroom_compress = None
        _HeadroomConfig = None  # type: ignore


def estimate_total_tokens(messages: list[dict]) -> int:
    return sum(_msg_tokens(m) for m in messages)


def compact_messages(messages: list[dict]) -> list[dict]:
    if len(messages) <= 2:
        return list(messages)

    total = estimate_total_tokens(messages)
    if total < CONTEXT_MAX_TOKENS * 0.7:
        return list(messages)

    if HAS_HEADROOM:
        result = _headroom_compact(messages)
        if result is not None:
            return result

    return _legacy_compact(messages)


def _headroom_compact(messages: list[dict]) -> list[dict] | None:
    from orca_code.config import (
        COMPRESS_MODEL, COMPRESS_USER_MSGS, COMPRESS_SYSTEM_MSGS,
        COMPRESS_PROTECT_RECENT, COMPRESS_TARGET_RATIO, MODEL, CONTEXT_MAX_TOKENS,
        console,
    )
    # Suppress headroom's own warnings about missing optional deps (transformers etc.)
    # since we handle the fallback gracefully ourselves.
    import logging as _logging
    _logging.getLogger("headroom").setLevel(_logging.ERROR)
    try:
        model = COMPRESS_MODEL or MODEL
        config = _HeadroomConfig(
            compress_user_messages=COMPRESS_USER_MSGS,
            compress_system_messages=COMPRESS_SYSTEM_MSGS,
            protect_recent=COMPRESS_PROTECT_RECENT,
            target_ratio=COMPRESS_TARGET_RATIO,
        )
        result = _headroom_compress(
            messages, model=model, model_limit=CONTEXT_MAX_TOKENS, config=config,
        )
        if result.compression_ratio > 0:
            applied = result.transforms_applied[:3] if result.transforms_applied else []
            tag = f" [{', '.join(applied)}]" if applied else ""
            console.print(
                f"[dim]Headroom: {result.tokens_before:,} → {result.tokens_after:,} tokens "
                f"({result.compression_ratio:.0%} reduction){tag}[/dim]"
            )
        return result.messages
    except Exception as e:
        console.print(f"[yellow]Headroom compression failed: {e}, using fallback[/yellow]")
        return None


def _legacy_compact(messages: list[dict]) -> list[dict]:
    system_msg = messages[0]
    turns: list[list[dict]] = []
    current_turn: list[dict] = []

    for m in messages[1:]:
        role = m.get("role", "")
        if role == "user" and current_turn:
            turns.append(current_turn)
            current_turn = [m]
        else:
            current_turn.append(m)
    if current_turn:
        turns.append(current_turn)

    if len(turns) <= KEEP_ROUNDS:
        return list(messages)

    keep_turns = turns[-KEEP_ROUNDS:]
    summarize_turns = turns[:-KEEP_ROUNDS]
    summary = _build_summary(summarize_turns)

    compacted: list[dict] = [system_msg]
    compacted.append({
        "role": "system",
        "content": f"[会话摘要 — 此前的 {len(summarize_turns)} 轮对话已压缩]\n\n{summary}",
    })
    for turn in keep_turns:
        compacted.extend(turn)
    return compacted


def _build_summary(turns: list[list[dict]]) -> str:
    summary_parts: list[str] = []
    tool_calls_summary: list[str] = []
    file_modifications: list[str] = []
    user_questions: list[str] = []
    key_findings: list[str] = []

    for i, turn in enumerate(turns):
        for m in turn:
            role = m.get("role", "")
            content = m.get("content", "") or ""

            if role == "user" and content:
                short = content[:120] + ("..." if len(content) > 120 else "")
                user_questions.append(f"  用户: {short}")

            elif role == "assistant":
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        fn = tc.get("function", {})
                        tname = fn.get("name", "?")
                        targs = str(fn.get("arguments", ""))[:80]
                        tool_calls_summary.append(f"  调用 {tname}({targs})")
                if content and len(content) > 50:
                    key_findings.append(f"  发现: {content[:150]}...")

            elif role == "tool":
                result_preview = content[:100] if content else "(empty)"
                if "wrote" in content.lower() or "written" in content.lower():
                    file_modifications.append(f"  修改: {result_preview}")

    if user_questions:
        summary_parts.append("用户问题:\n" + "\n".join(user_questions[-10:]))
    if tool_calls_summary:
        summary_parts.append("工具调用:\n" + "\n".join(tool_calls_summary[-20:]))
    if file_modifications:
        summary_parts.append("文件修改:\n" + "\n".join(file_modifications[-10:]))
    if key_findings:
        summary_parts.append("关键发现:\n" + "\n".join(key_findings[-10:]))

    if not summary_parts:
        return f"之前的 {len(turns)} 轮对话。细节已省略。"
    return "\n\n".join(summary_parts)


def maybe_compact(messages: list[dict]) -> list[dict]:
    total = estimate_total_tokens(messages)
    if total > CONTEXT_MAX_TOKENS * 0.7:
        from orca_code.config import console
        console.print(f"[yellow]⚠ 上下文接近限制 (~{total:,}/{CONTEXT_MAX_TOKENS:,} tokens)，正在压缩...[/yellow]")
        compacted = compact_messages(messages)
        new_total = estimate_total_tokens(compacted)
        savings = total - new_total
        console.print(f"[green]✓ 压缩完成: {total:,} → {new_total:,} tokens (节省 {savings:,})[/green]")
        return compacted
    return messages
