"""orca_code.latency_tracker — API latency percentile tracking (P2-64).

Tracks API call latencies with percentile calculation (p50/p95/p99).
Exposed via rate_tracker and health endpoint.

Usage:
    from orca_code.latency_tracker import LatencyTracker
    lt = LatencyTracker()
    lt.record(150)  # 150ms
    lt.record(320)
    print(lt.p95())  # 320.0
"""

from __future__ import annotations

import threading
import time
from collections import deque


class LatencyTracker:
    def __init__(self, max_samples: int = 1000):
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._lock = threading.Lock()
        self._min = float("inf")
        self._max = 0.0
        self._total = 0.0
        self._count = 0

    def record(self, latency_ms: float):
        with self._lock:
            self._samples.append(latency_ms)
            self._min = min(self._min, latency_ms)
            self._max = max(self._max, latency_ms)
            self._total += latency_ms
            self._count += 1

    def _percentile(self, p: float) -> float:
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * p / 100)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    def p50(self) -> float:
        return self._percentile(50)

    def p95(self) -> float:
        return self._percentile(95)

    def p99(self) -> float:
        return self._percentile(99)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "count": self._count,
                "avg_ms": round(self._total / max(self._count, 1), 1),
                "min_ms": round(self._min, 1) if self._count > 0 else 0,
                "max_ms": round(self._max, 1),
                "p50_ms": round(self.p50(), 1),
                "p95_ms": round(self.p95(), 1),
                "p99_ms": round(self.p99(), 1),
            }


_latency_tracker: LatencyTracker | None = None


def get_latency_tracker() -> LatencyTracker:
    global _latency_tracker
    if _latency_tracker is None:
        _latency_tracker = LatencyTracker()
    return _latency_tracker
