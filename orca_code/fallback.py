"""orca_code.fallback — Provider fallback chains and error recovery (P2-18).

Inspired by omp's retry.fallbackChains pattern.
When the primary model fails (429, 5xx, timeout), automatically try the next
provider in the chain before giving up.

Also provides:
  - Circuit breaker for failing tools (3 failures → skip for N minutes)
  - Request timeout with graceful degradation
  - Error classification (retryable vs fatal)
"""

from __future__ import annotations

import functools
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════════════
# Error classification
# ═══════════════════════════════════════════════════════════════════════════════

def is_retryable_error(error: Exception) -> bool:
    """Check if an API error is retryable (transient).

    Retryable: rate limits, server errors, timeouts, connection issues.
    Fatal: auth errors, bad requests, content filters.
    """
    error_str = str(error).lower()
    error_type = type(error).__name__

    # HTTP status codes embedded in error messages
    if "429" in error_str:
        return True  # Rate limit
    if any(s in error_str for s in ("500", "502", "503", "504")):
        return True  # Server error
    if any(s in error_str for s in ("timeout", "timed out", "connection")):
        return True  # Network issue
    if "overloaded" in error_str:
        return True

    # OpenAI-specific
    if "RateLimitError" in error_type:
        return True
    if "APITimeoutError" in error_type:
        return True
    if "APIConnectionError" in error_type:
        return True
    if "InternalServerError" in error_type:
        return True

    # Fatal errors
    if "401" in error_str or "403" in error_str:
        return False  # Auth error
    if "invalid_api_key" in error_str:
        return False
    if "content_filter" in error_str:
        return False

    return False


def classify_error(error: Exception) -> str:
    """Classify an error into a category string for logging/metrics."""
    error_str = str(error).lower()
    if "429" in error_str or "rate" in error_str:
        return "rate_limit"
    if any(s in error_str for s in ("500", "502", "503", "504")):
        return "server_error"
    if any(s in error_str for s in ("timeout", "timed out")):
        return "timeout"
    if any(s in error_str for s in ("connection", "refused")):
        return "connection"
    if "401" in error_str or "403" in error_str:
        return "auth"
    if "content_filter" in error_str:
        return "content_filter"
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# Provider fallback chain
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProviderEndpoint:
    """A provider endpoint in a fallback chain."""
    base_url: str
    api_key: str
    model: str
    label: str = ""


class FallbackChain:
    """Ordered list of provider endpoints with cooldown and retry logic.

    Usage:
        chain = FallbackChain([
            ProviderEndpoint("https://api.deepseek.com/v1", key1, "deepseek-chat", "primary"),
            ProviderEndpoint("https://api.openai.com/v1", key2, "gpt-4o", "fallback"),
        ])

        result = chain.call(lambda ep: make_api_call(ep))
    """

    def __init__(self, endpoints: list[ProviderEndpoint],
                 max_retries_per: int = 2,
                 cooldown_seconds: float = 60.0):
        self.endpoints = endpoints
        self.max_retries_per = max_retries_per
        self.cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, float] = {}  # label → cooldown_until timestamp
        self._lock = threading.Lock()

    def call(self, fn: Callable[[ProviderEndpoint], Any]) -> Any:
        """Try each endpoint in order until one succeeds.

        Args:
            fn: Function that takes a ProviderEndpoint and returns the result.

        Returns:
            The result from the first successful endpoint.

        Raises:
            RuntimeError: If all endpoints fail.
        """
        last_error: Exception | None = None

        for ep in self.endpoints:
            # Skip endpoints in cooldown
            with self._lock:
                cooldown_until = self._cooldowns.get(ep.label or ep.base_url, 0)
                if time.time() < cooldown_until:
                    continue

            for attempt in range(self.max_retries_per):
                try:
                    result = fn(ep)
                    # Success — clear cooldown
                    with self._lock:
                        self._cooldowns.pop(ep.label or ep.base_url, None)
                    return result
                except Exception as e:
                    last_error = e
                    if not is_retryable_error(e):
                        # Fatal error — don't retry this endpoint
                        break
                    if attempt < self.max_retries_per - 1:
                        backoff = 2 ** attempt  # 1s, 2s, 4s...
                        time.sleep(backoff)

            # Endpoint exhausted — put in cooldown
            with self._lock:
                self._cooldowns[ep.label or ep.base_url] = time.time() + self.cooldown_seconds

        raise RuntimeError(
            f"All {len(self.endpoints)} provider(s) failed. "
            f"Last error: {last_error}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit breaker for tools
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CircuitBreaker:
    """Circuit breaker for individual tools.

    After `failure_threshold` consecutive failures, the tool is skipped
    for `cooldown_seconds`. This prevents wasting tokens on tools that
    are consistently failing (e.g., network-dependent tools during outage).
    """
    failure_threshold: int = 3
    cooldown_seconds: float = 120.0
    _failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _open_until: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_open(self, tool_name: str) -> bool:
        """Check if the circuit is open (tool should be skipped)."""
        with self._lock:
            open_until = self._open_until.get(tool_name, 0)
            return time.time() < open_until

    def record_success(self, tool_name: str):
        """Record a successful tool execution — resets the circuit."""
        with self._lock:
            self._failures[tool_name] = 0
            self._open_until.pop(tool_name, None)

    def record_failure(self, tool_name: str):
        """Record a failed tool execution — may open the circuit."""
        with self._lock:
            self._failures[tool_name] += 1
            if self._failures[tool_name] >= self.failure_threshold:
                self._open_until[tool_name] = time.time() + self.cooldown_seconds

    def reset(self, tool_name: str | None = None):
        """Reset circuit for a specific tool or all tools."""
        with self._lock:
            if tool_name is None:
                self._failures.clear()
                self._open_until.clear()
            else:
                self._failures.pop(tool_name, None)
                self._open_until.pop(tool_name, None)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton instances
# ═══════════════════════════════════════════════════════════════════════════════

_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


def with_circuit_breaker(tool_name: str, fn: Callable[..., str]) -> Callable[..., str]:
    """Wrap a tool function with circuit breaker protection.

    If the circuit is open, returns an error message without calling the tool.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        cb = get_circuit_breaker()
        if cb.is_open(tool_name):
            return (f"错误: 工具 '{tool_name}' 暂时不可用 "
                    f"(连续失败 {cb.failure_threshold} 次，冷却中)。"
                    f"请稍后再试或使用其他工具。")
        try:
            result = fn(*args, **kwargs)
            cb.record_success(tool_name)
            return result
        except Exception as e:
            cb.record_failure(tool_name)
            raise

    return wrapper
