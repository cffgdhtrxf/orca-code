"""orca_code.rate_tracker — API rate limit and usage tracker (P2-38).

Tracks API call counts, token usage per minute/hour, and rate limit headers.
Provides usage statistics for status display and debugging.

Usage:
    from orca_code.rate_tracker import RateTracker

    tracker = RateTracker()
    tracker.record_call(input_tokens=1500, output_tokens=800)
    tracker.record_call(input_tokens=2000, output_tokens=1200)

    stats = tracker.get_stats()
    print(f"RPM: {stats['calls_per_minute']}, TPM: {stats['tokens_per_minute']}")
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class CallRecord:
    timestamp: float
    input_tokens: int
    output_tokens: int
    model: str = ""
    cached_tokens: int = 0


class RateTracker:
    """Tracks API usage with sliding window statistics.

    Thread-safe. Tracks:
      - Calls per minute (RPM)
      - Tokens per minute (TPM)
      - Total session usage
      - Peak usage
      - Cached tokens saved
    """

    def __init__(self, window_seconds: float = 60.0, max_records: int = 1000):
        self._window = window_seconds
        self._max_records = max_records
        self._records: deque[CallRecord] = deque()
        self._lock = threading.Lock()
        self._total_calls = 0
        self._total_input = 0
        self._total_output = 0
        self._total_cached = 0
        self._start_time = time.time()
        self._error_count = 0
        self._rate_limit_hits = 0

    def record_call(self, input_tokens: int = 0, output_tokens: int = 0,
                    model: str = "", cached_tokens: int = 0, latency_ms: float = 0):
        """Record an API call with token counts."""
        record = CallRecord(
            timestamp=time.time(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            cached_tokens=cached_tokens,
        )
        with self._lock:
            self._records.append(record)
            self._total_calls += 1
            self._total_input += input_tokens
            self._total_output += output_tokens
            self._total_cached += cached_tokens

            # Prune old records
            while len(self._records) > self._max_records:
                self._records.popleft()

    def record_error(self, is_rate_limit: bool = False):
        """Record an API error."""
        with self._lock:
            self._error_count += 1
            if is_rate_limit:
                self._rate_limit_hits += 1

    def get_window_stats(self) -> dict:
        """Get statistics for the sliding window period."""
        now = time.time()
        cutoff = now - self._window

        with self._lock:
            window_records = [r for r in self._records if r.timestamp > cutoff]
            calls = len(window_records)
            input_tok = sum(r.input_tokens for r in window_records)
            output_tok = sum(r.output_tokens for r in window_records)
            cached = sum(r.cached_tokens for r in window_records)

        return {
            "calls_per_minute": calls,
            "input_tokens_per_minute": input_tok,
            "output_tokens_per_minute": output_tok,
            "total_tokens_per_minute": input_tok + output_tok,
            "cached_tokens": cached,
        }

    def get_total_stats(self) -> dict:
        """Get cumulative session statistics."""
        with self._lock:
            uptime = time.time() - self._start_time
            return {
                "total_calls": self._total_calls,
                "total_input_tokens": self._total_input,
                "total_output_tokens": self._total_output,
                "total_cached_tokens": self._total_cached,
                "total_errors": self._error_count,
                "rate_limit_hits": self._rate_limit_hits,
                "uptime_seconds": uptime,
                "avg_input_per_call": self._total_input // max(self._total_calls, 1),
            }

    def get_stats(self) -> dict:
        """Get combined window + total statistics."""
        return {**self.get_window_stats(), **self.get_total_stats()}

    def format_stats(self) -> str:
        """Format statistics for display (one-liner)."""
        w = self.get_window_stats()
        t = self.get_total_stats()
        rpm = w["calls_per_minute"]
        tpm = w["total_tokens_per_minute"]
        total = t["total_input_tokens"] + t["total_output_tokens"]
        return (
            f"API: {t['total_calls']} calls, {total:,} tokens "
            f"({rpm} rpm, {tpm:,} tpm)"
            + (f", {t['rate_limit_hits']} rate-limit hits" if t["rate_limit_hits"] else "")
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_rate_tracker: RateTracker | None = None


def get_rate_tracker() -> RateTracker:
    global _rate_tracker
    if _rate_tracker is None:
        _rate_tracker = RateTracker()
    return _rate_tracker
