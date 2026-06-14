"""orca_code.structured_log — JSON-structured logging with rotation (P2-43).

Provides structured JSON log output for sessions, tool calls, and errors.
Rotates log files daily. Integrates with Python's logging module.

Log files (in logs/ directory):
  - session_YYYY-MM-DD.jsonl  — session lifecycle events
  - tools_YYYY-MM-DD.jsonl    — tool call records
  - errors_YYYY-MM-DD.jsonl   — error records

Usage:
    from orca_code.structured_log import log_tool_call, log_session_event, log_error
    log_tool_call("read_file", {"path": "/tmp"}, 150, True)
    log_session_event("turn_complete", {"turn": 3, "tokens": 500})
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredLogger:
    """Thread-safe JSONL logger with daily rotation."""

    def __init__(self, log_dir: Path | None = None):
        if log_dir is None:
            from orca_code.config import LOGS_DIR
            log_dir = LOGS_DIR / "structured"
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._date_cache: str = ""

    def _get_path(self, category: str) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"{category}_{today}.jsonl"

    def _write(self, category: str, record: dict):
        record["_ts"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            try:
                with open(self._get_path(category), "a", encoding="utf-8", errors="replace") as f:
                    f.write(line)
            except Exception:
                pass

    def tool_call(self, name: str, args: dict, duration_ms: float,
                  success: bool, result_len: int = 0):
        self._write("tools", {
            "event": "tool_call",
            "tool": name,
            "args_keys": list(args.keys())[:10],
            "duration_ms": round(duration_ms, 1),
            "success": success,
            "result_len": result_len,
        })

    def session_event(self, event: str, data: dict[str, Any] | None = None):
        self._write("sessions", {
            "event": event,
            "data": data or {},
        })

    def error(self, source: str, error_msg: str, context: dict | None = None):
        self._write("errors", {
            "source": source,
            "error": error_msg[:500],
            "context": context or {},
        })

    def api_call(self, model: str, input_tokens: int, output_tokens: int,
                 duration_ms: float, success: bool):
        self._write("api", {
            "event": "api_call",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": round(duration_ms, 1),
            "success": success,
        })

    def cleanup(self, max_age_days: int = 30):
        """Remove log files older than max_age_days."""
        cutoff = time.time() - max_age_days * 86400
        for f in self._dir.glob("*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass


# Singleton
_logger: StructuredLogger | None = None


def get_structured_logger() -> StructuredLogger:
    global _logger
    if _logger is None:
        _logger = StructuredLogger()
    return _logger


# Convenience functions
def log_tool_call(name: str, args: dict, duration_ms: float, success: bool, result_len: int = 0):
    get_structured_logger().tool_call(name, args, duration_ms, success, result_len)


def log_session_event(event: str, **data):
    get_structured_logger().session_event(event, data)


def log_error(source: str, error_msg: str, **context):
    get_structured_logger().error(source, error_msg, context)


def log_api_call(model: str, input_tokens: int, output_tokens: int, duration_ms: float, success: bool):
    get_structured_logger().api_call(model, input_tokens, output_tokens, duration_ms, success)
