"""orca_code.session_compaction — Context window compaction (P1-7).

Inspired by omp's compaction system (packages/agent/src/compaction/).
Auto-triggers when token count exceeds threshold. Summarizes early turns
and injects summary as a system message.

Strategy:
  - When total tokens > CONTEXT_MAX_TOKENS * 0.7, trigger compaction
  - Keep last KEEP_ROUNDS turns fully intact
  - Summarize older turns into a structured summary
  - Inject summary as a synthetic system message after the real system prompt
"""

from __future__ import annotations

from orca_code.config import CONTEXT_MAX_TOKENS, KEEP_ROUNDS
from orca_code.session_messages import _msg_tokens


def estimate_total_tokens(messages: list[dict]) -> int:
    """Estimate total token count for a message list."""
    return sum(_msg_tokens(m) for m in messages)


def compact_messages(messages: list[dict]) -> list[dict]:
    """Compress conversation history to fit within token budget.

    Keeps the system prompt, recent KEEP_ROUNDS turns intact,
    and replaces older turns with a terse summary.

    Returns a new list — does not modify the original.
    """
    if len(messages) <= 2:
        return list(messages)  # nothing to compact

    total = estimate_total_tokens(messages)
    if total < CONTEXT_MAX_TOKENS * 0.7:
        return list(messages)  # under threshold, no compaction needed

    # Build turn structure: each turn = user → assistant → [tool results ...]
    # System message is always message[0] and is preserved.
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

    # Keep last KEEP_ROUNDS turns intact
    keep_turns = turns[-KEEP_ROUNDS:]
    summarize_turns = turns[:-KEEP_ROUNDS]

    # Build summary from older turns
    summary = _build_summary(summarize_turns)

    # Reconstruct: system → summary → ...kept turns
    compacted: list[dict] = [system_msg]
    compacted.append({
        "role": "system",
        "content": f"[会话摘要 — 此前的 {len(summarize_turns)} 轮对话已压缩]\n\n{summary}",
    })
    for turn in keep_turns:
        compacted.extend(turn)

    return compacted


def _build_summary(turns: list[list[dict]]) -> str:
    """Build a structured summary from older conversation turns.

    Extracts: user questions, tool calls made, key outputs,
    file modifications, decisions reached.
    """
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
                tc_id = m.get("tool_call_id", "")
                result_preview = content[:100] if content else "(empty)"
                if "Error" in result_preview or "错误" in result_preview:
                    result_preview = f"ERROR: {result_preview}"
                # Track file modifications
                if "wrote" in content.lower() or "written" in content.lower():
                    file_modifications.append(f"  修改: {result_preview}")

    # Assemble summary
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
    """Check token usage and compact if needed. Returns (possibly) compacted list."""
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
