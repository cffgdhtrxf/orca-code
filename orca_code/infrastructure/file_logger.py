"""orca_code.infrastructure.file_logger — JSON-structured file logger.

Writes structured JSON lines to logs/orca-YYYY-MM-DD.jsonl.
Subscribes to EventBus for automatic tool execution logging.

Usage:
    from orca_code.infrastructure.file_logger import attach_file_logger
    attach_file_logger()  # auto-logs all tool events to file
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


class FileLogger:
    """Append-only JSONL logger with daily rotation."""

    def __init__(self, log_dir: Optional[Path] = None):
        self._log_dir = log_dir or (Path(__file__).parent.parent.parent / "logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_date = ""

    def _get_path(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        self._current_date = today
        return self._log_dir / f"orca-{today}.jsonl"

    def log(self, event_type: str, data: dict) -> None:
        """Append a structured log line."""
        entry = {
            "ts": datetime.now().isoformat(),
            "type": event_type,
            **data,
        }
        with self._lock:
            path = self._get_path()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass  # Never crash on logging failure

    def attach_to_bus(self, bus=None) -> "FileLogger":
        """Subscribe to EventBus for automatic logging."""
        from orca_code.core.event_bus import get_event_bus, EventType

        if bus is None:
            bus = get_event_bus()
        logger = self

        @bus.on(EventType.TOOL_START)
        def _log_start(event):
            d = event.data or {}
            logger.log("tool_start", {
                "tool": d.get("name", "?"),
            })

        @bus.on(EventType.TOOL_RESULT)
        def _log_result(event):
            d = event.data or {}
            logger.log("tool_result", {
                "tool": d.get("name", "?"),
                "elapsed_ms": round(d.get("elapsed_ms", 0), 1),
                "result_length": d.get("result_length", 0),
            })

        @bus.on(EventType.TOOL_ERROR)
        def _log_error(event):
            d = event.data or {}
            logger.log("tool_error", {
                "tool": d.get("name", "?"),
                "elapsed_ms": round(d.get("elapsed_ms", 0), 1),
                "error": str(d.get("error", ""))[:500],
            })

        @bus.on(EventType.TURN_START)
        def _log_turn(event):
            d = event.data or {}
            logger.log("turn_start", {"turn": d.get("turn", 0)})

        @bus.on(EventType.TURN_END)
        def _log_turn_end(event):
            d = event.data or {}
            logger.log("turn_end", {
                "turn": d.get("turn", 0),
                "tokens": d.get("tokens", 0),
            })

        return self


# Singleton
_logger: Optional[FileLogger] = None
_logger_lock = threading.Lock()


def get_file_logger(log_dir: Optional[Path] = None) -> FileLogger:
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = FileLogger(log_dir)
    return _logger


def attach_file_logger(bus=None, log_dir: Optional[Path] = None) -> FileLogger:
    """One-call setup: create file logger and attach to EventBus."""
    return get_file_logger(log_dir).attach_to_bus(bus)
