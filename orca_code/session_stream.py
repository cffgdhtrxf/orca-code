"""orca_code.session_stream — LLM API calling, stream processing, and tool execution.

Extracted from session.py.
"""

from __future__ import annotations

import json
import time
import logging
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai
import tenacity

from rich.markdown import Markdown
from rich.padding import Padding

from orca_code.config import (MODEL, BASE_URL, API_KEY,
    IS_DEEPSEEK, IS_LOCAL, IS_MULTIMODAL, USE_SIMPLE_PROMPT,
    ENABLE_THINK_MODE, REASONING_EFFORT, MAX_OUTPUT_TOKENS,
    MAX_WORKERS, client, console)
from orca_code.utils import _sanitize_ansi, fix_truncated_json
from orca_code.tool_registry import TOOLS, TOOL_MAP, run_tool
from orca_code.session_messages import sanitize_messages, smart_trim_messages, _msg_tokens


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
    # Track streaming markdown for live rendering
    from rich.live import Live
    from rich.spinner import Spinner
    live_display = None

    for chunk in stream:
        if not chunk.choices:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = chunk.usage
            continue

        delta = chunk.choices[0].delta

        if hasattr(delta, "reasoning_content") and delta.reasoning_content:
            if not thinking_started:
                console.print()
                # Rich native dim/italic thinking indicator
                console.print("[dim italic]💭 ", end="")
                thinking_started = True
            display = _sanitize_ansi(delta.reasoning_content.replace("\n", "\n  "))
            console.print(f"[dim italic]{display}[/dim italic]", end="")
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
                # Use Rich Live for streaming markdown preview
                live_display = Live(
                    Markdown("", code_theme="monokai"),
                    console=console,
                    refresh_per_second=8,
                    transient=False,
                )
                live_display.start()
            answer_full += delta.content
            elapsed = time.time() - t_answer_start
            # Update the live display with partial markdown
            if live_display:
                status_line = f"[dim]⏳ {len(answer_full)} 字"
                if elapsed >= 1:
                    status_line += f" · {elapsed:.0f}s"
                status_line += "[/dim]\n\n"
                live_display.update(Markdown(status_line + answer_full, code_theme="monokai"))

    if reasoning_full:
        session.last_thinking = reasoning_full

    # Clean up thinking display
    if thinking_started:
        console.print()

    if live_display is not None:
        live_display.stop()

    if answer_full:
        console.print("[bold white]●[/bold white] ", end="")
        md = Markdown(answer_full, code_theme="monokai")
        console.print(Padding(md, (0, 0, 0, 2)))
    else:
        console.print()

    return reasoning_full, answer_full, tool_calls_by_index, usage
def execute_tool_calls(tool_calls_by_index):
    from orca_code.tool_registry import run_tool
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
        try:
            result = run_tool(fn_name, fn_args)
            elapsed = (time.time() - t0) * 1000
            show_tool_result(result, fn_name)
            show_tool_done(elapsed)
        except KeyboardInterrupt:
            result = "(interrupted)"
            elapsed = (time.time() - t0) * 1000
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