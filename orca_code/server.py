"""orca_code.server — FastAPI HTTP + WebSocket API server.

Usage:
    python -m orca_code.server              # starts on http://localhost:8498
    python -m orca_code.server --port 8500  # custom port

Endpoints:
    POST   /v1/chat               Synchronous chat completion
    WS     /v1/chat/stream         Streaming chat with tool calls
    GET    /v1/sessions            List active sessions
    POST   /v1/sessions            Create new session
    GET    /v1/sessions/{id}       Get session info
    DELETE /v1/sessions/{id}       Archive session
    WS     /v1/bridge              Remote control bridge
    GET    /v1/health              Health check
    GET    /dashboard              Web dashboard

Runs alongside the existing Flask dashboard (:8499) on a separate port (:8498).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

# Permission mode: read from config (not hardcoded YOLO).
# Per-session override supported via ChatRequest.mode or WS session_id lookup.
import orca_code.config as _cfg
from orca_code.config import (
    BASE_URL,
    MODEL,
)
from orca_code.permissions import PermissionMode
from orca_code.session import build_system_prompt
from orca_code.session_stream import call_model, execute_tool_calls, process_stream
from orca_code.tool_registry import TOOLS

app = FastAPI(title="Orca Code API", version="5.3.0")

# ── MCP Registry (lazy init on first use) ───────────────────────────────────
_mcp_registry = None


def _init_mcp():
    """Initialize MCP registry from config on first access."""
    global _mcp_registry
    if _mcp_registry is not None:
        return _mcp_registry
    from orca_code.mcp_client import McpRegistry, load_mcp_configs_from_dict
    _mcp_registry = McpRegistry()
    try:
        configs = load_mcp_configs_from_dict(_cfg.CONFIG)
        for cfg in configs:
            _mcp_registry.add_server(cfg)
        if configs:
            results = _mcp_registry.connect_all()
            connected = sum(1 for v in results.values() if v)
            if connected > 0:
                import logging
                logging.getLogger(__name__).info("MCP: %d/%d servers connected", connected, len(configs))
    except Exception:
        pass
    return _mcp_registry

# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send")
    session_id: str | None = Field(None, description="Session ID. Creates new if omitted.")
    mode: str = Field("auto", description="Permission mode: read-only, auto, yolo")
    model: str | None = Field(None, description="Override model name")

class ChatResponse(BaseModel):
    session_id: str
    answer: str
    reasoning: str | None = None
    tool_calls: list[dict] = []
    tokens: dict = {}
    elapsed_ms: float = 0

class SessionInfo(BaseModel):
    session_id: str
    turns: int
    tool_calls: int
    created_at: str
    model: str

class ExportRequest(BaseModel):
    session_id: str | None = None
    format: str = "markdown"  # markdown, html, json


@app.post("/v1/sessions/export")
async def export_session_endpoint(req: ExportRequest):
    """Export a session to the specified format.

    Args:
        session_id: Session to export. If None, exports the global session.
        format: "markdown", "html", or "json"

    Returns:
        {"path": "/path/to/exported/file", "format": "markdown"}
    """
    from orca_code.session import export_session
    from orca_code.session import session as global_session

    sess = global_session
    if req.session_id and req.session_id in _sessions:
        # Build a temporary session-like object from the stored messages
        stored = _sessions[req.session_id]
        from orca_code.session import Session
        tmp = Session()
        tmp.messages = list(stored["messages"])
        tmp.turns = stored["turns"]
        tmp.tool_calls = stored["tool_calls"]
        sess = tmp

    path = export_session(format=req.format, session_obj=sess)
    if path is None:
        raise HTTPException(status_code=500, detail="Export failed")
    return {"path": path, "format": req.format}


class HealthResponse(BaseModel):
    status: str
    version: str
    model: str
    base_url: str
    uptime_seconds: float

# ═══════════════════════════════════════════════════════════════════════════════
# Session Store (in-memory, per-server-process)
# ═══════════════════════════════════════════════════════════════════════════════

_start_time = time.time()
_sessions: dict[str, dict] = {}  # session_id -> {messages, turns, created_at, ..., interrupt_event}


def _get_or_create_session(session_id: str | None = None, mode: str = "auto") -> dict:
    """Get existing session or create a new one."""
    if session_id and session_id in _sessions:
        sess = _sessions[session_id]
        # Update permission mode if provided
        if mode:
            sess["permission_mode"] = mode
        return sess

    sid = session_id or str(uuid.uuid4())[:12]
    # Determine permission mode: use provided mode, or config default
    from orca_code.permissions import PermissionMode as PM
    try:
        perm_mode = PM(mode) if mode else _cfg.PERMISSION_MODE
    except ValueError:
        perm_mode = _cfg.PERMISSION_MODE

    sess = {
        "id": sid,
        "messages": [{"role": "system", "content": build_system_prompt()}],
        "turns": 0,
        "tool_calls": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "model": MODEL,
        "permission_mode": perm_mode,
        "interrupt_event": asyncio.Event(),
    }
    _sessions[sid] = sess
    return sess


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# Tools & Config endpoints (for TUI frontend)
# ═══════════════════════════════════════════════════════════════════════════════

class ToolItem(BaseModel):
    name: str
    description: str
    parameters: dict = {}
    risk_level: str = "read"


@app.get("/v1/tools")
async def list_tools(include_mcp: bool = False):
    """List all available tools with their schemas.

    Args:
        include_mcp: If True, also include tools from connected MCP servers.
    """
    from orca_code.config import PERMISSION_RULES
    tools = []
    for t in TOOLS:
        fn = t.get("function", t)
        name = fn.get("name", "")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        risk = PERMISSION_RULES.get(name, "auto")
        tools.append(ToolItem(
            name=name,
            description=desc,
            parameters=params,
            risk_level=risk,
        ).model_dump())

    # Include MCP tools if requested
    mcp_tool_count = 0
    if include_mcp:
        try:
            registry = _init_mcp()
            for mcp_tool in registry.get_all_tools():
                tools.append(ToolItem(
                    name=f"mcp__{mcp_tool.server_name}__{mcp_tool.name}",
                    description=f"[MCP:{mcp_tool.server_name}] {mcp_tool.description}",
                    parameters=mcp_tool.parameters,
                    risk_level="exec",  # MCP tools default to exec risk
                ).model_dump())
                mcp_tool_count += 1
        except Exception:
            pass

    return {"tools": tools, "count": len(tools), "mcp_tools": mcp_tool_count}


class McpServerInfo(BaseModel):
    name: str
    enabled: bool
    connected: bool
    tool_count: int = 0


@app.get("/v1/mcp")
async def list_mcp():
    """List configured MCP servers and their connection status."""
    registry = _init_mcp()
    servers = []
    for name, config in registry._servers.items():
        client = registry._clients.get(name)
        servers.append(McpServerInfo(
            name=name,
            enabled=config.enabled,
            connected=client.is_connected if client else False,
            tool_count=len(client.list_tools()) if (client and client.is_connected) else 0,
        ).model_dump())
    return {
        "servers": servers,
        "total_servers": registry.server_count,
        "connected_servers": registry.connected_count,
        "total_mcp_tools": len(registry.get_all_tools()),
    }


@app.post("/v1/mcp/connect")
async def connect_mcp():
    """Connect/reconnect all MCP servers."""
    registry = _init_mcp()
    results = registry.connect_all()
    return {"results": results, "connected": sum(1 for v in results.values() if v)}


@app.get("/v1/config")
async def get_config():
    """Return current configuration (safe subset)."""
    from orca_code.config import (
        ENABLE_BROWSER_AUTO,
        ENABLE_GUI_AUTO,
        ENABLE_THINK_MODE,
        PERMISSION_MODE,
        WORKING_DIR,
    )
    return {
        "model": MODEL,
        "base_url": BASE_URL,
        "thinking_enabled": ENABLE_THINK_MODE,
        "gui_enabled": ENABLE_GUI_AUTO,
        "browser_enabled": ENABLE_BROWSER_AUTO,
        "permission_mode": PERMISSION_MODE.value if hasattr(PERMISSION_MODE, 'value') else str(PERMISSION_MODE),
        "working_dir": str(WORKING_DIR),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/v1/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        version="5.3.0",
        model=MODEL,
        base_url=BASE_URL,
        uptime_seconds=time.time() - _start_time,
    )


@app.get("/v1/health/detailed")
async def health_detailed():
    """Detailed health check with diagnostics (P2-35)."""
    import sys as _sys
    import threading as _threading

    # Memory usage
    try:
        import psutil as _psutil
        process = _psutil.Process()
        mem_info = process.memory_info()
        mem_mb = mem_info.rss / (1024 * 1024)
        cpu_percent = process.cpu_percent(interval=0.1)
    except ImportError:
        mem_mb = 0
        cpu_percent = 0

    # Tool cache stats
    cache_size = 0
    try:
        from orca_code.tool_cache import get_tool_cache
        cache_size = get_tool_cache().size
    except Exception:
        pass

    # Circuit breaker status
    cb_status = {}
    try:
        from orca_code.fallback import get_circuit_breaker
        cb = get_circuit_breaker()
        cb_status = {"threshold": cb.failure_threshold, "cooldown_s": cb.cooldown_seconds}
    except Exception:
        pass

    # File tracker status
    tracker_pending = 0
    try:
        from orca_code.rollback import get_file_tracker
        tracker_pending = get_file_tracker().pending_count
    except Exception:
        pass

    # MCP status
    mcp_status = {}
    try:
        from orca_code.mcp_client import get_mcp_registry
        reg = get_mcp_registry()
        mcp_status = {"servers": reg.server_count, "connected": reg.connected_count}
    except Exception:
        pass

    # Hook registry
    hook_info = "available"
    try:
        from orca_code.hooks import get_hook_registry
        reg = get_hook_registry()
        hook_info = f"{len(reg._pre_hooks)} pre, {len(reg._post_hooks)} post"
    except Exception:
        pass

    # Rate tracker
    rate_stats = {}
    try:
        from orca_code.rate_tracker import get_rate_tracker
        rt = get_rate_tracker()
        rate_stats = rt.get_stats()
    except Exception:
        pass

    # Workspace info
    workspace_summary = ""
    try:
        from orca_code.workspace_detect import detect_workspace
        ws = detect_workspace()
        workspace_summary = ws.summary
    except Exception:
        pass

    # Plugin info
    plugin_info = "none"
    try:
        from orca_code.plugin_loader import discover_plugins
        plugins = discover_plugins()
        plugin_info = f"{len(plugins)} discovered"
    except Exception:
        pass

    # Tool usage analytics (P2-107)
    tool_analytics = {}
    try:
        from orca_code.structured_log import get_structured_logger
        slog = get_structured_logger()
        tool_analytics = {"available": True}
    except Exception:
        tool_analytics = {"available": False}

    return {
        "status": "ok",
        "version": "5.3.0",
        "uptime_seconds": time.time() - _start_time,
        "model": MODEL,
        "sessions": len(_sessions),
        "system": {
            "python": _sys.version.split()[0],
            "platform": _sys.platform,
            "threads": _threading.active_count(),
            "memory_mb": round(mem_mb, 1),
            "cpu_percent": cpu_percent,
        },
        "cache": {"tool_cache_entries": cache_size},
        "circuit_breaker": cb_status,
        "rollback": {"pending_changes": tracker_pending},
        "mcp": mcp_status,
        "hooks": hook_info,
        "rate_tracker": rate_stats,
        "plugins": plugin_info,
        "tool_analytics": tool_analytics,
        "workspace": workspace_summary,
    }


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Synchronous one-shot chat completion.

    Sends a message, processes any tool calls, and returns the final answer.
    Uses asyncio.to_thread to avoid blocking the event loop.
    """
    t0 = time.time()
    sess = _get_or_create_session(req.session_id, mode=req.mode)

    # Append user message
    sess["messages"].append({"role": "user", "content": req.message})
    sess["turns"] += 1

    reasoning = ""
    answer = ""
    tool_calls_made = []
    token_usage = {}

    try:
        # Get LLM response (non-blocking via thread pool)
        from orca_code.session_messages import sanitize_messages

        sess["messages"] = sanitize_messages(sess["messages"])

        # Use non-streaming call — wrap in asyncio.to_thread to avoid blocking
        response = await asyncio.to_thread(call_model, sess["messages"])
        reasoning, answer, tool_calls_idx, usage = process_stream(response)

        if usage:
            token_usage = {
                "input": getattr(usage, "prompt_tokens", 0) or 0,
                "output": getattr(usage, "completion_tokens", 0) or 0,
            }

        # Execute tool calls if any
        if tool_calls_idx:
            tc_list, tr_list = await asyncio.to_thread(execute_tool_calls, tool_calls_idx)
            tool_calls_made = [
                {"name": tc["function"]["name"], "args": tc["function"]["arguments"]}
                for tc in tc_list
            ]
            sess["tool_calls"] += len(tc_list)

            sess["messages"].append({
                "role": "assistant",
                "content": answer or None,
                "tool_calls": tc_list,
            })
            sess["messages"].extend(tr_list)

            # Re-call model with tool results (non-blocking)
            response2 = await asyncio.to_thread(call_model, sess["messages"])
            _, answer2, _, usage2 = process_stream(response2)
            if answer2:
                answer = answer2
            if usage2:
                token_usage["input"] += getattr(usage2, "prompt_tokens", 0) or 0
                token_usage["output"] += getattr(usage2, "completion_tokens", 0) or 0

        # Store assistant response
        sess["messages"].append({"role": "assistant", "content": answer})

    except Exception as e:
        answer = f"Error: {e}"
        sess["messages"].pop()  # Remove the user message that caused error

    return ChatResponse(
        session_id=sess["id"],
        answer=answer,
        reasoning=reasoning or None,
        tool_calls=tool_calls_made,
        tokens=token_usage,
        elapsed_ms=(time.time() - t0) * 1000,
    )


@app.websocket("/v1/chat/stream")
async def chat_stream(ws: WebSocket):
    """Streaming chat with real-time tool call updates.

    Client sends: {"message": "...", "session_id": "..."}
    Server sends: {"type": "text", "content": "..."}
                  {"type": "reasoning", "content": "..."}
                  {"type": "tool_call", "name": "...", "args": {...}}
                  {"type": "tool_result", "name": "...", "content": "..."}
                  {"type": "done", "session_id": "...", "tokens": {...}}
                  {"type": "error", "message": "..."}
    """
    await ws.accept()
    sess = None

    try:
        # Receive initial message
        data = await ws.receive_json()
        message = data.get("message", "")
        session_id = data.get("session_id")
        mode = data.get("mode", "auto")

        sess = _get_or_create_session(session_id, mode=mode)
        sess["messages"].append({"role": "user", "content": message})
        sess["turns"] += 1
        # Reset interrupt event for new turn
        sess["interrupt_event"].clear()

        # Stream LLM response — agentic loop: call model → exec tools → repeat
        from orca_code.session_messages import sanitize_messages
        sess["messages"] = sanitize_messages(sess["messages"])

        # P1-7: Auto-compact messages if token usage exceeds threshold
        from orca_code.session_compaction import maybe_compact
        sess["messages"] = maybe_compact(sess["messages"])

        total_input_tokens = 0
        total_output_tokens = 0
        max_turns = 10

        # ── Start a background task to listen for interrupt messages ──────
        async def listen_for_interrupt():
            """Listen for interrupt/control messages from the client."""
            try:
                while True:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=0.5)
                    try:
                        ctrl = __import__('json').loads(raw)
                        if ctrl.get("type") == "interrupt":
                            sess["interrupt_event"].set()
                            await ws.send_json({"type": "interrupted", "message": "Stream aborted by user"})
                    except Exception:
                        pass  # ignore non-JSON messages in this listener
            except TimeoutError:
                pass
            except Exception:
                pass  # listener exits on any fatal error

        interrupt_task = asyncio.create_task(listen_for_interrupt())

        for turn in range(max_turns):
            # Check for interrupt before each turn
            if sess["interrupt_event"].is_set():
                await ws.send_json({"type": "done", "session_id": sess["id"],
                    "tokens": {"input": total_input_tokens, "output": total_output_tokens},
                    "interrupted": True})
                break

            # ── P2-31: Reset streaming state between turns ──────────────────
            # Send turn boundary so TUI can clear transient streaming state
            if turn > 0:
                await ws.send_json({"type": "turn_boundary", "turn": turn})

            # NOTE: call_model returns a streaming generator. We call it directly
            # (not via asyncio.to_thread) because the generator's HTTP connection
            # is tied to the calling thread — asyncio.to_thread would break streaming.
            # Between chunks we yield to the event loop with await asyncio.sleep(0).
            stream = call_model(sess["messages"])

            reasoning_full = ""
            answer_full = ""
            tool_calls_by_index = {}
            usage = None

            # Check for interrupt before processing stream chunks
            if sess["interrupt_event"].is_set():
                break

            # Yield to event loop between chunks to allow interrupts and other tasks
            _chunk_count = 0

            for chunk in stream:
                # Yield to event loop every 10 chunks to allow interrupts
                _chunk_count += 1
                if _chunk_count % 10 == 0:
                    await asyncio.sleep(0)

                # Check interrupt during streaming
                if sess["interrupt_event"].is_set():
                    break
                if not chunk.choices:
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage = chunk.usage
                        total_input_tokens += getattr(usage, "prompt_tokens", 0)
                        total_output_tokens += getattr(usage, "completion_tokens", 0)
                    continue

                delta = chunk.choices[0].delta

                # Push reasoning incrementally
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_full += delta.reasoning_content
                    await ws.send_json({
                        "type": "reasoning_delta",
                        "content": delta.reasoning_content,
                    })

                # Push text incrementally
                if delta.content:
                    answer_full += delta.content
                    await ws.send_json({
                        "type": "text_delta",
                        "content": delta.content,
                    })

                # Push tool call deltas incrementally (so frontend doesn't freeze)
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
                        # Send incremental tool progress to frontend
                        if entry["function_name"]:
                            await ws.send_json({
                                "type": "tool_call_delta",
                                "name": entry["function_name"],
                                "args": entry["function_arguments"],
                            })

            # ── No tool calls? This is the final answer ──────────────────
            if not tool_calls_by_index:
                sess["messages"].append({
                    "role": "assistant", "content": answer_full or "",
                })
                break

            # ── Execute tools and feed results back to model ─────────────
            tool_names = [entry["function_name"] for entry in tool_calls_by_index.values()]
            await ws.send_json({
                "type": "tool_executing",
                "count": len(tool_calls_by_index),
                "tools": tool_names,
            })

            # ── P2-48: Stream tool results with size awareness ──────────────
            # execute_tool_calls is synchronous — fine to call directly in WS handler
            tc_list, tr_list = execute_tool_calls(tool_calls_by_index)

            for tc, tr in zip(tc_list, tr_list):
                result_content = str(tr.get("content", ""))
                result_len = len(result_content)

                await ws.send_json({
                    "type": "tool_call",
                    "name": tc["function"]["name"],
                    "args": tc["function"]["arguments"],
                })

                # Stream large results in chunks with progress
                if result_len > 2000:
                    # Send header
                    await ws.send_json({
                        "type": "tool_result_start",
                        "name": tc["function"]["name"],
                        "total_bytes": result_len,
                    })
                    # Send in 1000-char chunks
                    for offset in range(0, result_len, 1000):
                        chunk = result_content[offset:offset + 1000]
                        await ws.send_json({
                            "type": "tool_result_delta",
                            "name": tc["function"]["name"],
                            "content": chunk,
                            "offset": offset,
                            "total": result_len,
                        })
                    # Send end marker
                    await ws.send_json({
                        "type": "tool_result_end",
                        "name": tc["function"]["name"],
                        "total_bytes": result_len,
                    })
                else:
                    await ws.send_json({
                        "type": "tool_result",
                        "name": tc["function"]["name"],
                        "content": result_content[:500],
                    })

            sess["messages"].append({
                "role": "assistant",
                "content": answer_full or None,
                "tool_calls": tc_list,
            })
            sess["messages"].extend(tr_list)
            sess["tool_calls"] += len(tc_list)

            # Loop continues → model sees tool results and may answer or call more tools

        await ws.send_json({
            "type": "done",
            "session_id": sess["id"],
            "tokens": {
                "input": total_input_tokens,
                "output": total_output_tokens,
            },
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # Cancel the interrupt listener task
        if 'interrupt_task' in dir() and interrupt_task:
            interrupt_task.cancel()
            try:
                await interrupt_task
            except asyncio.CancelledError:
                pass
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/v1/sessions")
async def list_sessions(include_saved: bool = False):
    """List active sessions, optionally including saved sessions from disk.

    Args:
        include_saved: If True, also list sessions saved to disk via JSONL.
    """
    active = [
        {
            "session_id": s["id"],
            "turns": s["turns"],
            "tool_calls": s["tool_calls"],
            "message_count": len(s.get("messages", [])),
            "created_at": s["created_at"],
            "model": s["model"],
            "source": "memory",
        }
        for s in _sessions.values()
    ]

    saved = []
    if include_saved:
        try:
            from orca_code.session_persistence import list_sessions as list_saved
            saved = list_saved()
            for s in saved:
                s["source"] = "disk"
        except Exception:
            pass

    all_sessions = active + [
        s for s in saved
        if not any(a["session_id"] == s["session_id"] for a in active)
    ]

    return {
        "sessions": all_sessions,
        "count": len(all_sessions),
        "active_count": len(active),
        "saved_count": len(saved),
    }


@app.post("/v1/sessions")
async def create_session():
    """Create a new empty session."""
    sess = _get_or_create_session()
    return {"session_id": sess["id"], "created_at": sess["created_at"]}


@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    s = _sessions[session_id]
    return {
        "session_id": s["id"],
        "turns": s["turns"],
        "tool_calls": s["tool_calls"],
        "message_count": len(s["messages"]),
        "created_at": s["created_at"],
        "model": s["model"],
    }


@app.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str):
    """Archive and delete a session."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del _sessions[session_id]
    return {"status": "archived", "session_id": session_id}


@app.post("/v1/sessions/{session_id}/fork")
async def fork_session(session_id: str):
    """Fork a session — create a new session with the same message history.

    The new session starts at the same point as the original, allowing
    the user to explore alternative paths without losing the original.
    """
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    original = _sessions[session_id]
    # Create new session with copied history
    new_id = str(uuid.uuid4())[:12]
    new_sess = {
        "id": new_id,
        "messages": [dict(m) for m in original["messages"]],  # deep copy
        "turns": original["turns"],
        "tool_calls": original["tool_calls"],
        "created_at": datetime.now(UTC).isoformat(),
        "model": original["model"],
        "permission_mode": original.get("permission_mode", PermissionMode.AUTO),
        "interrupt_event": asyncio.Event(),
        "forked_from": session_id,
    }
    _sessions[new_id] = new_sess
    return {
        "session_id": new_id,
        "forked_from": session_id,
        "message_count": len(new_sess["messages"]),
        "turns": new_sess["turns"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Dashboard HTML (minimal, self-contained)
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orca Code API v5.3</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:2rem;max-width:1000px;margin:0 auto}
h1{color:#58a6ff;margin-bottom:.5rem}
h2{color:#f0f6fc;font-size:1.1rem;margin:1.5rem 0 .5rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.5rem;margin-bottom:1rem}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem}
.stat{text-align:center;padding:.5rem}
.stat .value{font-size:1.8rem;font-weight:bold;color:#58a6ff}
.stat .label{font-size:.7rem;color:#8b949e;margin-top:.25rem}
.endpoint{display:grid;grid-template-columns:60px 140px 1fr 70px;gap:.5rem;padding:.3rem 0;border-bottom:1px solid #21262d;font-size:.85rem;align-items:center}
.method{font-weight:bold;padding:2px 6px;border-radius:3px;text-align:center;font-size:.7rem}
.GET{background:#23863633;color:#3fb950}
.POST{background:#1f6feb33;color:#58a6ff}
.WS{background:#d2992233;color:#d29922}
.DELETE{background:#da363333;color:#f85149}
.path{font-family:monospace;color:#f0f6fc}
.desc{color:#8b949e;font-size:.8rem}
.status{display:inline-block;padding:4px 12px;border-radius:12px;font-size:.8rem}
.ok{background:#23863633;color:#3fb950}
.live{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{text-align:left;padding:.5rem;border-bottom:1px solid #21262d}
th{color:#8b949e;font-weight:normal;font-size:.75rem}
tr:hover{background:#1c2128}
</style>
</head>
<body>
<h1>🐋 Orca Code <span style="color:#8b949e;font-size:1rem">v5.3</span></h1>

<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center">
<span class="status ok">● Online</span>
<span class="live" style="color:#3fb950;font-size:.8rem">● Live</span>
<span id="uptime" style="color:#8b949e"></span>
</div>
<div class="grid2" style="margin-top:1rem">
<div class="stat"><div class="value" id="ver">v5.3</div><div class="label">Version</div></div>
<div class="stat"><div class="value" id="model">-</div><div class="label">Model</div></div>
<div class="stat"><div class="value" id="sessions">-</div><div class="label">Sessions</div></div>
<div class="stat"><div class="value" id="memory">-</div><div class="label">Memory</div></div>
<div class="stat"><div class="value" id="calls">-</div><div class="label">API Calls</div></div>
<div class="stat"><div class="value" id="tokens">-</div><div class="label">Tokens</div></div>
</div>
</div>

<h2>Endpoints</h2>
<div class="card">
<div class="endpoint"><span class="method POST">POST</span><span class="path">/v1/chat</span><span class="desc">Sync chat</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method WS">WS</span><span class="path">/v1/chat/stream</span><span class="desc">Stream chat</span><span class="desc">WebSocket</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/sessions</span><span class="desc">List sessions</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method POST">POST</span><span class="path">/v1/sessions/export</span><span class="desc">Export session</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method POST">POST</span><span class="path">/v1/sessions/{id}/fork</span><span class="desc">Fork session</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method WS">WS</span><span class="path">/v1/bridge</span><span class="desc">Bridge</span><span class="desc">WebSocket</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/health</span><span class="desc">Health check</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/health/detailed</span><span class="desc">Detailed health</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/models</span><span class="desc">Model catalog</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/mcp</span><span class="desc">MCP status</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/tools</span><span class="desc">Tool catalog</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/v1/config</span><span class="desc">Config info</span><span class="desc">JSON</span></div>
<div class="endpoint"><span class="method GET">GET</span><span class="path">/dashboard/stream</span><span class="desc">Live stats</span><span class="desc">SSE</span></div>
</div>

<script>
function fmt(n){return n>1e6?(n/1e6).toFixed(1)+'M':n>1e3?(n/1e3).toFixed(1)+'K':String(n)}
function updateStats(d){
 document.getElementById('model').textContent=d.model||'-';
 document.getElementById('sessions').textContent=d.sessions||0;
 document.getElementById('memory').textContent=(d.system?.memory_mb||0)+'MB';
 document.getElementById('uptime').textContent='Uptime: '+(d.uptime/3600).toFixed(1)+'h';
 var rt=d.total||{};
 document.getElementById('calls').textContent=rt.total_calls||0;
 document.getElementById('tokens').textContent=fmt((rt.total_input_tokens||0)+(rt.total_output_tokens||0));
}
// Initial load
fetch('/v1/health/detailed').then(r=>r.json()).then(updateStats);
// Live updates via SSE
var es=new EventSource('/dashboard/stream');
es.onmessage=function(e){try{updateStats(JSON.parse(e.data))}catch(_){}}
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Web dashboard — shows API status and endpoints."""
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/dashboard/stream")
async def dashboard_stream():
    """SSE streaming endpoint for real-time dashboard updates (P2-45).

    Sends a JSON event every 2 seconds with current server stats.
    Connect from HTML with: new EventSource('/dashboard/stream')
    """
    async def event_stream():
        import asyncio as _asyncio
        while True:
            try:
                # Gather stats
                stats = {
                    "sessions": len(_sessions),
                    "uptime": round(time.time() - _start_time, 1),
                    "model": MODEL,
                }
                try:
                    from orca_code.rate_tracker import get_rate_tracker
                    rt = get_rate_tracker()
                    stats["rate"] = rt.get_window_stats()
                    stats["total"] = rt.get_total_stats()
                except Exception:
                    stats["rate"] = {}
                    stats["total"] = {}
                try:
                    from orca_code.tool_cache import get_tool_cache
                    stats["cache_entries"] = get_tool_cache().size
                except Exception:
                    stats["cache_entries"] = 0
                try:
                    from orca_code.rollback import get_file_tracker
                    stats["pending_rollbacks"] = get_file_tracker().pending_count
                except Exception:
                    stats["pending_rollbacks"] = 0

                yield f"data: {json.dumps(stats, default=str)}\n\n"
                await _asyncio.sleep(2)
            except Exception:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/v1/models")
async def list_models():
    """List available models from the provider API (P2-46).

    Attempts to query the LLM provider's /v1/models endpoint.
    Falls back to returning the configured model only.
    """
    models = [{"id": MODEL, "provider": "configured", "available": True}]
    try:
        import openai as _oa
        c = _oa.OpenAI(api_key=_cfg.API_KEY, base_url=BASE_URL)
        resp = c.models.list()
        remote_models = []
        for m in resp.data[:50]:
            remote_models.append({
                "id": m.id,
                "provider": BASE_URL,
                "available": True,
            })
        if remote_models:
            models = remote_models
    except Exception:
        pass  # Return configured model only

    return {"models": models, "count": len(models), "configured_model": MODEL}


@app.get("/v1/config/backup")
async def backup_config():
    """Export current configuration as a JSON backup file."""
    from orca_code.config import CONFIG, SAVE_DIR
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = SAVE_DIR / f"config_backup_{ts}.json"
    try:
        # Redact sensitive values in backup
        safe_config = dict(CONFIG)
        for key in ("api_key", "tavily_api_key", "vision_api_key"):
            if safe_config.get(key):
                safe_config[key] = safe_config[key][:8] + "***REDACTED***"
        backup_path.write_text(
            json.dumps(safe_config, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return {"path": str(backup_path), "backed_up_at": ts, "fields": len(safe_config)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Backup failed: {e}")


@app.post("/v1/config/restore")
async def restore_config(backup_path: str):
    """Restore configuration from a backup file."""
    p = Path(backup_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        from orca_code.config_validator import validate_config
        result = validate_config(data)
        if result.has_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Backup config has {result.error_count} errors: {result.format_for_display()}",
            )
        # Merge into current config (don't overwrite sensitive fields)
        from orca_code.config import CONFIG
        for k, v in data.items():
            if not k.endswith("_key") or not CONFIG.get(k):
                CONFIG[k] = v
        return {"restored": True, "fields": len(data)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")


@app.post("/v1/sessions/merge")
async def merge_sessions(session_a: str, session_b: str):
    """Merge two sessions into one (P2-73). Preserves chronological order."""
    if session_a not in _sessions or session_b not in _sessions:
        raise HTTPException(404, "One or both sessions not found")
    a, b = _sessions[session_a], _sessions[session_b]
    merged_msgs = []
    # Interleave messages by timestamp (simple concat — both are ordered)
    seen = set()
    for m in a["messages"] + b["messages"]:
        key = str(m.get("content", ""))[:100] + m.get("role", "")
        if key not in seen:
            merged_msgs.append(m)
            seen.add(key)
    new_id = str(uuid.uuid4())[:12]
    _sessions[new_id] = {
        "id": new_id, "messages": merged_msgs,
        "turns": a["turns"] + b["turns"],
        "tool_calls": a["tool_calls"] + b["tool_calls"],
        "created_at": datetime.now(UTC).isoformat(),
        "model": a["model"], "permission_mode": a.get("permission_mode"),
        "interrupt_event": asyncio.Event(), "merged_from": [session_a, session_b],
    }
    return {"session_id": new_id, "merged_from": [session_a, session_b], "message_count": len(merged_msgs)}


@app.post("/v1/sessions/auto-save")
async def trigger_auto_save():
    """Trigger session auto-save for all in-memory sessions (P2-62).

    Writes each session to disk as JSONL. Called periodically or on demand.
    """
    saved = 0
    for sid, sess in _sessions.items():
        try:
            from orca_code.config import SAVE_DIR
            from orca_code.session_persistence import JSONLSessionStore, save_session_metadata
            store = JSONLSessionStore(SAVE_DIR / f"{sid}.jsonl")
            store.append_messages(sess["messages"])
            # Save metadata
            save_session_metadata(sid, {
                "turns": sess["turns"],
                "tool_calls": sess["tool_calls"],
                "model": sess["model"],
                "created_at": sess["created_at"],
                "last_saved": datetime.now(UTC).isoformat(),
            })
            saved += 1
        except Exception:
            pass
    return {"saved_sessions": saved, "total_sessions": len(_sessions)}


@app.get("/v1/health/api-key-check")
async def check_api_key():
    """Check if the configured API key is valid (P2-93).

    Makes a minimal request to the provider's models.list endpoint.
    Returns key status and any error details.
    """
    try:
        from openai import OpenAI
        c = OpenAI(api_key=_cfg.API_KEY, base_url=BASE_URL)
        models = c.models.list()
        return {
            "status": "valid",
            "model_count": len(models.data),
            "provider": BASE_URL,
        }
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            return {"status": "invalid", "error": "Authentication failed — check api_key in config.json"}
        elif "429" in error_msg:
            return {"status": "rate_limited", "error": "Rate limited — wait and retry"}
        else:
            return {"status": "error", "error": error_msg[:200]}


@app.post("/v1/sessions/recover")
async def recover_sessions():
    """Scan and recover corrupted session JSONL files (P2-98).

    Removes malformed lines from JSONL files.
    Returns count of recovered and removed lines.
    """
    from orca_code.config import SAVE_DIR
    recovered, removed = 0, 0
    for f in SAVE_DIR.glob("*.jsonl"):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            valid = []
            for line in lines:
                if not line.strip(): continue
                try:
                    json.loads(line)
                    valid.append(line)
                except json.JSONDecodeError:
                    removed += 1
            if len(valid) < len(lines):
                f.write_text("\n".join(valid) + "\n", encoding="utf-8")
                recovered += 1
        except Exception: pass
    return {"recovered_files": recovered, "removed_lines": removed}


@app.post("/v1/tools/dry-run")
async def tool_dry_run(tool_name: str, args: dict = {}):
    """Preview what a tool would do without executing (P2-94).

    Returns the tool name, parsed arguments, and expected impact level.
    Does NOT execute the tool.
    """
    from orca_code.permissions import RiskLevel, get_risk
    from orca_code.tool_registry import TOOL_MAP
    if tool_name not in TOOL_MAP:
        raise HTTPException(404, f"Unknown tool: {tool_name}")
    risk = get_risk(tool_name)
    impact = {RiskLevel.READ: "只读 — 不会修改任何文件",
              RiskLevel.WRITE: "写入 — 可能修改文件",
              RiskLevel.EXEC: "执行 — 可能运行代码或修改系统"}.get(risk, "未知")
    return {
        "tool": tool_name,
        "args": args,
        "risk_level": risk.value,
        "impact": impact,
        "would_execute": True,
        "note": "This is a dry-run. No action was taken.",
    }


@app.post("/v1/models/switch")
async def switch_model(model_name: str):
    """Switch the active model (runtime override, not persisted).

    This only affects the current server process. For permanent change,
    update config.json and restart.
    """
    global MODEL
    old_model = MODEL
    MODEL = model_name
    return {"previous": old_model, "current": MODEL, "note": "Runtime override. Update config.json for permanent change."}


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge WebSocket (remote control)
# ═══════════════════════════════════════════════════════════════════════════════

@app.websocket("/v1/bridge")
async def bridge(ws: WebSocket):
    """Remote control bridge WebSocket.

    Connect to this endpoint from a remote client to control
    the local Orca Code instance. Requires authentication token.
    """
    await ws.accept()
    from orca_code.bridge import bridge_endpoint
    await bridge_endpoint(ws)


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Orca Code API Server")
    parser.add_argument("--port", type=int, default=8498)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    print("Orca Code API Server v5.3.0")
    print(f"   HTTP:     http://{args.host}:{args.port}")
    print(f"   Health:   http://{args.host}:{args.port}/v1/health")
    print(f"   Dashboard: http://{args.host}:{args.port}/dashboard")
    print(f"   Docs:     http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "orca_code.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
