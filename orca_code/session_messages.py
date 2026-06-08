"""orca_code.session_messages — Message sanitization, compression, and token estimation.

Extracted from session.py. No UI or streaming dependencies.
"""

from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from orca_code.config import (CONFIG, CONTEXT_MAX_TOKENS, KEEP_ROUNDS,
    HAS_MEMORY, mem_mgr, console)
from orca_code.utils import _estimate_tokens, _sanitize_ansi, _strip_html
from orca_code.tool_registry import TOOLS, TOOL_MAP


def _get_tools():
    return TOOLS

def _get_tool_map():
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
