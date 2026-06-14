"""orca_code.infrastructure.metrics — Tool execution timing and session metrics.

Collects timing data via EventBus subscribers. Provides p50/p95/p99 stats.
Thread-safe, minimal overhead (<1ms per tool call).

Usage:
    from orca_code.infrastructure.metrics import MetricsCollector
    collector = MetricsCollector()
    collector.attach_to_bus()  # auto-subscribes to TOOL_START/RESULT/ERROR
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class MetricsCollector:
    """Collects per-tool timing data and aggregate statistics.

    Subscribes to EventBus events and records elapsed time for each
    tool execution. Provides percentile queries for dashboard display.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: dict[str, float] = {}  # event_id → start_time
        self._timings: dict[str, list[float]] = defaultdict(list)  # tool_name → [elapsed_ms]
        self._errors: dict[str, int] = defaultdict(int)  # tool_name → error_count
        self._total_calls = 0
        self._total_errors = 0
        self._session_start = time.time()

    def record_start(self, tool_name: str, event_id: str) -> None:
        """Record that a tool execution started."""
        with self._lock:
            self._pending[event_id] = time.time()

    def record_result(self, tool_name: str, event_id: str, elapsed_ms: float = 0) -> None:
        """Record that a tool execution completed successfully."""
        with self._lock:
            start = self._pending.pop(event_id, None)
            if start is not None and elapsed_ms == 0:
                elapsed_ms = (time.time() - start) * 1000
            self._timings[tool_name].append(elapsed_ms)
            self._total_calls += 1
            # Keep only last 1000 samples per tool
            if len(self._timings[tool_name]) > 1000:
                self._timings[tool_name] = self._timings[tool_name][-1000:]

    def record_error(self, tool_name: str, event_id: str, elapsed_ms: float = 0) -> None:
        """Record that a tool execution failed."""
        with self._lock:
            start = self._pending.pop(event_id, None)
            if start is not None and elapsed_ms == 0:
                elapsed_ms = (time.time() - start) * 1000
            self._timings[tool_name].append(elapsed_ms)
            self._errors[tool_name] += 1
            self._total_calls += 1
            self._total_errors += 1

    def get_tool_stats(self, tool_name: str) -> dict[str, Any] | None:
        """Get statistics for a specific tool."""
        with self._lock:
            timings = self._timings.get(tool_name, [])
            if not timings:
                return None
            return {
                "tool": tool_name,
                "calls": len(timings),
                "errors": self._errors.get(tool_name, 0),
                "p50_ms": _percentile(timings, 50),
                "p95_ms": _percentile(timings, 95),
                "p99_ms": _percentile(timings, 99),
                "min_ms": min(timings),
                "max_ms": max(timings),
                "avg_ms": sum(timings) / len(timings),
            }

    def get_all_stats(self) -> list[dict[str, Any]]:
        """Get statistics for all tools, sorted by call count descending."""
        with self._lock:
            stats = []
            for name in self._timings:
                s = self.get_tool_stats(name)
                if s:
                    stats.append(s)
            stats.sort(key=lambda x: x["calls"], reverse=True)
            return stats

    def get_top_slowest(self, n: int = 5) -> list[dict[str, Any]]:
        """Get the N slowest tools by p95 latency."""
        stats = self.get_all_stats()
        stats.sort(key=lambda x: x["p95_ms"], reverse=True)
        return stats[:n]

    def get_summary(self) -> dict[str, Any]:
        """Get a session-level summary."""
        with self._lock:
            elapsed = time.time() - self._session_start
            all_timings = []
            for t in self._timings.values():
                all_timings.extend(t)

            return {
                "uptime_seconds": int(elapsed),
                "total_calls": self._total_calls,
                "total_errors": self._total_errors,
                "error_rate": (
                    self._total_errors / self._total_calls
                    if self._total_calls > 0 else 0
                ),
                "unique_tools": len(self._timings),
                "p50_ms": _percentile(all_timings, 50) if all_timings else 0,
                "p95_ms": _percentile(all_timings, 95) if all_timings else 0,
            }

    def attach_to_bus(self, bus=None) -> MetricsCollector:
        """Attach this collector to the global EventBus.

        Subscribes to TOOL_START, TOOL_RESULT, TOOL_ERROR events.
        Returns self for chaining.
        """
        from orca_code.core.event_bus import EventType, get_event_bus

        if bus is None:
            bus = get_event_bus()

        collector = self

        @bus.on(EventType.TOOL_START)
        def _on_start(event):
            data = event.data or {}
            event_id = f"{data.get('name', '?')}_{event.timestamp}"
            collector.record_start(data.get("name", "?"), event_id)

        @bus.on(EventType.TOOL_RESULT)
        def _on_result(event):
            data = event.data or {}
            event_id = f"{data.get('name', '?')}_{event.timestamp}"
            collector.record_result(
                data.get("name", "?"), event_id,
                data.get("elapsed_ms", 0),
            )

        @bus.on(EventType.TOOL_ERROR)
        def _on_error(event):
            data = event.data or {}
            event_id = f"{data.get('name', '?')}_{event.timestamp}"
            collector.record_error(
                data.get("name", "?"), event_id,
                data.get("elapsed_ms", 0),
            )

        return self


# ─── Singleton ───────────────────────────────────────────────────────────────

_collector: MetricsCollector | None = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector


# ─── Math helper ─────────────────────────────────────────────────────────────

def _percentile(data: list[float], percentile: float) -> float:
    """Compute the percentile using linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * percentile / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
    return sorted_data[f]
