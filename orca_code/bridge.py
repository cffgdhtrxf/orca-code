"""orca_code.bridge — WebSocket bridge for remote control.

Enables controlling a local Orca Code instance from a remote client
(e.g., web UI, mobile app, or another CLI instance).

Protocol (JSON over WebSocket):
    Client → Server:
        {"type":"auth","token":"<jwt_or_local_token>"}
        {"type":"chat","message":"...","session_id":"...","mode":"auto"}
        {"type":"permission","tool_name":"execute_command","decision":"allow"}
        {"type":"ping"}

    Server → Client:
        {"type":"auth_ok","session_id":"abc123"}
        {"type":"auth_error","message":"Invalid token"}
        {"type":"text","content":"..."}
        {"type":"reasoning","content":"..."}
        {"type":"tool_call","name":"...","args":{...}}
        {"type":"tool_result","name":"...","content":"..."}
        {"type":"permission_request","tool_name":"...","risk":"exec","args":{...}}
        {"type":"done","tokens":{...}}
        {"type":"error","message":"..."}
        {"type":"pong"}

Authentication:
    - Local token: stored in ~/.orca/bridge_token (auto-generated on first run)
    - The token is printed at startup: "Bridge token: xxxxx"
    - Client sends {"type":"auth","token":"xxxxx"} as first message

Usage:
    Start with bridge:
        python -m orca_code.bridge --port 8499
    Or from server.py (bridge is under /v1/bridge WebSocket endpoint)
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

from orca_code.config import (
    MODEL,
)
from orca_code.permissions import RiskLevel

# ═══════════════════════════════════════════════════════════════════════════════
# Token Management
# ═══════════════════════════════════════════════════════════════════════════════

TOKEN_FILE = Path.home() / ".orca" / "bridge_token"


def get_or_create_token() -> str:
    """Get the existing bridge token or create a new one."""
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token

    token = secrets.token_hex(32)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


def validate_token(token: str) -> bool:
    """Validate a bridge token (constant-time comparison)."""
    expected = get_or_create_token()
    if len(token) != len(expected):
        return False
    # Constant-time comparison
    result = 0
    for a, b in zip(token.encode(), expected.encode()):
        result |= a ^ b
    return result == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Permission Request Queue (for remote approval)
# ═══════════════════════════════════════════════════════════════════════════════

class PermissionQueue:
    """Queue for permission requests that need remote approval.

    When a tool needs permission and we're in bridge mode (no local prompt),
    the request is queued here and the bridge client is asked to approve.
    """

    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0

    async def request(self, tool_name: str, args: dict, risk: RiskLevel, timeout: float = 30) -> str:
        """Queue a permission request. Returns 'allow', 'deny', or 'timeout'."""
        req_id = f"perm_{self._counter}"
        self._counter += 1

        future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except TimeoutError:
            self._pending.pop(req_id, None)
            return "deny"  # Timeout = deny

    def resolve(self, req_id: str, decision: str):
        """Resolve a pending permission request."""
        future = self._pending.pop(req_id, None)
        if future and not future.done():
            future.set_result(decision)


# Global permission queue for bridge mode
_bridge_perm_queue = PermissionQueue()


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Handler
# ═══════════════════════════════════════════════════════════════════════════════

class BridgeHandler:
    """Handles a single bridge WebSocket connection.

    One handler per connected client. Manages authentication,
    message routing, and stream processing.
    """

    def __init__(self, ws, session_store: dict):
        self.ws = ws
        self._sessions = session_store
        self._authenticated = False
        self._session_id: str | None = None
        self._ping_task: asyncio.Task | None = None

    async def handle(self):
        """Main handler loop. Reads messages and dispatches."""
        # Start ping keepalive
        self._ping_task = asyncio.create_task(self._ping_loop())

        try:
            async for raw in self.ws.iter_text():
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send({"type": "error", "message": "Invalid JSON"})
                    continue

                await self._dispatch(msg)
        except Exception:
            pass
        finally:
            if self._ping_task:
                self._ping_task.cancel()

    async def _dispatch(self, msg: dict):
        msg_type = msg.get("type", "")

        if msg_type == "auth":
            await self._handle_auth(msg)
        elif msg_type == "ping":
            await self._send({"type": "pong", "ts": time.time()})
        elif not self._authenticated:
            await self._send({"type": "auth_error", "message": "Not authenticated"})
        elif msg_type == "chat":
            await self._handle_chat(msg)
        elif msg_type == "permission":
            await self._handle_permission(msg)
        else:
            await self._send({"type": "error", "message": f"Unknown message type: {msg_type}"})

    async def _handle_auth(self, msg: dict):
        token = msg.get("token", "")
        if validate_token(token):
            self._authenticated = True
            self._session_id = msg.get("session_id") or secrets.token_hex(6)
            await self._send({"type": "auth_ok", "session_id": self._session_id})
        else:
            await self._send({"type": "auth_error", "message": "Invalid token"})

    async def _handle_chat(self, msg: dict):
        """Process a chat message through the bridge."""
        message = msg.get("message", "")
        session_id = msg.get("session_id", self._session_id)

        if not message.strip():
            await self._send({"type": "error", "message": "Empty message"})
            return

        sess = self._get_or_create_session(session_id)
        sess["messages"].append({"role": "user", "content": message})
        sess["turns"] += 1

        try:
            from orca_code.session_messages import sanitize_messages, smart_trim_messages
            from orca_code.session_stream import call_model, execute_tool_calls, process_stream

            sess["messages"] = sanitize_messages(sess["messages"])
            sess["messages"] = smart_trim_messages(sess["messages"])

            stream = call_model(sess["messages"])
            reasoning, answer, tool_calls_idx, usage = process_stream(stream)

            if reasoning:
                await self._send({"type": "reasoning", "content": reasoning})
            if answer:
                await self._send({"type": "text", "content": answer})

            # Execute tool calls (with remote permission)
            if tool_calls_idx:
                tc_list, tr_list = execute_tool_calls(tool_calls_idx)
                for tc, tr in zip(tc_list, tr_list):
                    await self._send({
                        "type": "tool_call",
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                    })
                    await self._send({
                        "type": "tool_result",
                        "name": tc["function"]["name"],
                        "content": str(tr.get("content", ""))[:500],
                    })

                sess["messages"].append({
                    "role": "assistant", "content": answer or None,
                    "tool_calls": tc_list,
                })
                sess["messages"].extend(tr_list)
                sess["tool_calls"] += len(tc_list)

            sess["messages"].append({"role": "assistant", "content": answer or ""})

            await self._send({
                "type": "done",
                "tokens": {
                    "input": getattr(usage, "prompt_tokens", 0) if usage else 0,
                    "output": getattr(usage, "completion_tokens", 0) if usage else 0,
                },
            })

        except Exception as e:
            sess["messages"].pop()  # Remove user message
            await self._send({"type": "error", "message": str(e)})

    async def _handle_permission(self, msg: dict):
        """Handle a permission decision from the remote client."""
        req_id = msg.get("request_id", "")
        decision = msg.get("decision", "deny")
        _bridge_perm_queue.resolve(req_id, decision)

    def _get_or_create_session(self, session_id: str) -> dict:
        if session_id in self._sessions:
            return self._sessions[session_id]
        from orca_code.session import build_system_prompt
        sess = {
            "id": session_id,
            "messages": [{"role": "system", "content": build_system_prompt()}],
            "turns": 0,
            "tool_calls": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "model": MODEL,
        }
        self._sessions[session_id] = sess
        return sess

    async def _send(self, data: dict):
        try:
            await self.ws.send_json(data)
        except Exception:
            pass

    async def _ping_loop(self, interval: int = 15):
        """Send periodic pings to keep the connection alive."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.ws.send_json({"type": "ping", "ts": time.time()})
            except Exception:
                break


# ═══════════════════════════════════════════════════════════════════════════════
# Bridge Endpoint (for FastAPI integration)
# ═══════════════════════════════════════════════════════════════════════════════

_bridge_sessions: dict[str, dict] = {}


async def bridge_endpoint(ws):
    """FastAPI WebSocket endpoint handler for /v1/bridge.

    Usage in server.py:
        @app.websocket("/v1/bridge")
        async def bridge(ws: WebSocket):
            await ws.accept()
            from orca_code.bridge import bridge_endpoint
            await bridge_endpoint(ws)
    """
    handler = BridgeHandler(ws, _bridge_sessions)
    await handler.handle()


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone bridge server
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Run a standalone bridge server (WebSocket only, no HTTP routes)."""
    import argparse

    import uvicorn
    from fastapi import FastAPI, WebSocket

    parser = argparse.ArgumentParser(description="Orca Code Bridge Server")
    parser.add_argument("--port", type=int, default=8499)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    app = FastAPI(title="Orca Code Bridge")

    @app.websocket("/v1/bridge")
    async def bridge(ws: WebSocket):
        await ws.accept()
        await bridge_endpoint(ws)

    @app.get("/v1/health")
    async def health():
        return {"status": "ok", "bridge": "active"}

    TOKEN = get_or_create_token()
    print("🐋 Orca Code Bridge")
    print(f"   WS:  ws://{args.host}:{args.port}/v1/bridge")
    print(f"   Token: {TOKEN}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
