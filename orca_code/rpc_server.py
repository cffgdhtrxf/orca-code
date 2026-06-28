"""orca_code.rpc_server — JSON-RPC stdin/stdout server for TypeScript embedding.

Replaces WebSocket with direct stdin/stdout JSON-RPC protocol.
One JSON object per line (ndjson). TypeScript spawns this as a subprocess.

Usage:
    python -m orca_code.rpc_server
    # Then write JSON-RPC requests to stdin, read responses from stdout.

Protocol:
    → {"id":1, "method":"chat", "params":{"message":"hello", "session_id":"abc"}}
    ← {"id":1, "type":"reasoning_delta", "content":"..."}
    ← {"id":1, "type":"text_delta", "content":"..."}
    ← {"id":1, "type":"tool_call_delta", "name":"...", "args":"..."}
    ← {"id":1, "type":"tool_executing", "count":1, "tools":["read_file"]}
    ← {"id":1, "type":"done", "session_id":"abc", "tokens":{"input":100,"output":50}}

Methods:
    chat          — Send message, get streaming response
    health        — Health check
    tools/list    — List available tools
    config/get    — Get current config
    sessions/list — List active sessions
    permission_response — Send permission decision back to backend
    shutdown      — Graceful shutdown
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime

# RPC mode: default to YOLO (no interactive permission prompt over stdin/stdout).
# The TypeScript TUI will handle permissions when the PermissionCard UI is ready.
import orca_code.config as _cfg

# ═══════════════════════════════════════════════════════════════════════════════
# Core imports (same as server.py)
# ═══════════════════════════════════════════════════════════════════════════════
from orca_code.config import BASE_URL, MODEL
from orca_code.permissions import PermissionMode
from orca_code.session import build_system_prompt
from orca_code.session_stream import call_model, execute_tool_calls
from orca_code.tool_registry import TOOLS

_cfg.PERMISSION_MODE = PermissionMode.YOLO

# ═══════════════════════════════════════════════════════════════════════════════
# Session store (same as server.py)
# ═══════════════════════════════════════════════════════════════════════════════

_sessions: dict[str, dict] = {}

def _get_or_create_session(session_id: str | None = None) -> dict:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    sid = session_id or str(uuid.uuid4())[:12]
    sess = {
        "id": sid,
        "messages": [{"role": "system", "content": build_system_prompt()}],
        "turns": 0, "tool_calls": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "model": MODEL,
    }
    _sessions[sid] = sess
    return sess

# ═══════════════════════════════════════════════════════════════════════════════
# JSON-RPC handler
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize_str(s: str) -> str:
    """Remove lone surrogates that can't be encoded to UTF-8."""
    return s.encode('utf-8', errors='replace').decode('utf-8', errors='replace')

def _sanitize_dict(d: dict) -> dict:
    """Recursively sanitize all string values in a dict."""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _sanitize_str(v)
        elif isinstance(v, dict):
            result[k] = _sanitize_dict(v)
        elif isinstance(v, list):
            result[k] = [_sanitize_str(x) if isinstance(x, str) else x for x in v]
        else:
            result[k] = v
    return result

def _write(obj: dict):
    """Write a JSON line to stdout. Handles surrogate characters safely."""
    try:
        safe = _sanitize_dict(obj)
        line = json.dumps(safe, ensure_ascii=False, default=str) + "\n"
        sys.stdout.buffer.write(line.encode('utf-8', errors='replace'))
        sys.stdout.buffer.flush()
    except Exception:
        # Ultimate fallback
        sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True, default=str) + "\n").encode('ascii', errors='replace'))
        sys.stdout.buffer.flush()

def _send_event(req_id: int, event_type: str, **kwargs):
    # Sanitize any string kwargs before sending
    safe_kwargs = {}
    for k, v in kwargs.items():
        if isinstance(v, str):
            safe_kwargs[k] = _sanitize_str(v)
        else:
            safe_kwargs[k] = v
    _write({"id": req_id, "type": event_type, **safe_kwargs})

def handle_chat(req_id: int, params: dict):
    """Handle chat method — streaming response."""
    message = params.get("message", "")
    session_id = params.get("session_id")

    sess = _get_or_create_session(session_id)
    sess["messages"].append({"role": "user", "content": message})
    sess["turns"] += 1

    from orca_code.session_messages import sanitize_messages
    sess["messages"] = sanitize_messages(sess["messages"])

    from orca_code.session_compaction import maybe_compact
    sess["messages"] = maybe_compact(sess["messages"])

    total_input = 0
    total_output = 0

    for turn in range(10):
        # call_model returns a streaming generator — call directly (not via thread)
        try:
            stream = call_model(sess["messages"])
        except Exception as e:
            _send_event(req_id, "error", message=f"API call failed: {e}")
            break

        reasoning_full = ""
        answer_full = ""
        tool_calls_by_index = {}

        for chunk in stream:
            if not chunk.choices:
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage
                    total_input += getattr(usage, "prompt_tokens", 0) or 0
                    total_output += getattr(usage, "completion_tokens", 0) or 0
                continue

            delta = chunk.choices[0].delta

            # Reasoning delta
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_full += delta.reasoning_content
                _send_event(req_id, "reasoning_delta", content=delta.reasoning_content)

            # Text delta
            if delta.content:
                answer_full += delta.content
                _send_event(req_id, "text_delta", content=delta.content)

            # Tool call delta
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {"id": "", "function_name": "", "function_arguments": ""}
                    entry = tool_calls_by_index[idx]
                    if tc.id: entry["id"] = tc.id
                    if tc.function and tc.function.name: entry["function_name"] = tc.function.name
                    if tc.function and tc.function.arguments: entry["function_arguments"] += tc.function.arguments
                    if entry["function_name"]:
                        _send_event(req_id, "tool_call_delta", name=entry["function_name"], args=entry["function_arguments"])

        # No tool calls → final answer
        if not tool_calls_by_index:
            sess["messages"].append({"role": "assistant", "content": answer_full or ""})
            break

        # Execute tools — send permission-relevant info for TUI display
        tool_names = [e["function_name"] for e in tool_calls_by_index.values()]
        from orca_code.permissions import get_risk
        tool_risks = {name: get_risk(name).value for name in tool_names}
        _send_event(req_id, "tool_executing", count=len(tool_calls_by_index), tools=tool_names, risks=tool_risks)

        tc_list, tr_list = execute_tool_calls(tool_calls_by_index)

        for tc, tr in zip(tc_list, tr_list):
            _send_event(req_id, "tool_call", name=tc["function"]["name"], args=tc["function"]["arguments"])
            _send_event(req_id, "tool_result", name=tc["function"]["name"], content=str(tr.get("content", ""))[:500])

        sess["messages"].append({"role": "assistant", "content": answer_full or None, "tool_calls": tc_list})
        sess["messages"].extend(tr_list)
        sess["tool_calls"] += len(tc_list)

    _send_event(req_id, "done", session_id=sess["id"], tokens={"input": total_input, "output": total_output})
    # Safeguard: if loop exited due to max_turns, mark as potentially incomplete
    if turn >= 9:
        _send_event(req_id, "text_delta", content="\n\n[已达到最大轮次限制 (10)]")

def handle_health(req_id: int, params: dict):
    _send_event(req_id, "health_result", status="ok", version="5.3.0", model=MODEL, base_url=BASE_URL)

def handle_tools_list(req_id: int, params: dict):
    tools = [{
        "name": t.get("function", t).get("name", ""),
        "description": t.get("function", t).get("description", ""),
        "parameters": t.get("function", t).get("parameters", {}),
    } for t in TOOLS]
    _send_event(req_id, "tools_result", tools=tools, count=len(tools))

def handle_config_get(req_id: int, params: dict):
    from orca_code.config import (
        ENABLE_BROWSER_AUTO,
        ENABLE_GUI_AUTO,
        ENABLE_THINK_MODE,
        PERMISSION_MODE,
        WORKING_DIR,
    )
    _send_event(req_id, "config_result", model=MODEL, base_url=BASE_URL,
                thinking_enabled=ENABLE_THINK_MODE, gui_enabled=ENABLE_GUI_AUTO,
                browser_enabled=ENABLE_BROWSER_AUTO, permission_mode=str(PERMISSION_MODE),
                working_dir=str(WORKING_DIR))

def handle_sessions_list(req_id: int, params: dict):
    sessions = [{"session_id": s["id"], "turns": s["turns"], "tool_calls": s["tool_calls"],
                 "created_at": s["created_at"], "model": s["model"]} for s in _sessions.values()]
    _send_event(req_id, "sessions_result", sessions=sessions, count=len(sessions))

# ═══════════════════════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════════════════════

METHODS = {
    "chat": handle_chat,
    "health": handle_health,
    "tools/list": handle_tools_list,
    "config/get": handle_config_get,
    "sessions/list": handle_sessions_list,
}

def main():
    """Run the JSON-RPC stdin/stdout server loop."""
    # Force UTF-8 on stdout to avoid GBK encoding errors on Windows
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        _sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    # Signal ready to parent process
    _write({"type": "ready", "version": "5.3.0", "model": MODEL})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = request.get("id", 0)
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "shutdown":
            _send_event(req_id, "shutdown_ack")
            break

        handler = METHODS.get(method)
        if handler:
            try:
                handler(req_id, params)
            except Exception as e:
                _send_event(req_id, "error", message=str(e))
        else:
            _send_event(req_id, "error", message=f"Unknown method: {method}")

if __name__ == "__main__":
    main()
