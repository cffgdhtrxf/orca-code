"""orca_code.response_cache — LLM response caching (P2-49).

Caches LLM responses keyed by (model, messages_hash, tools_hash, temperature).
Significantly reduces token usage for repeated or similar queries.

Cache strategy:
  - SHA256 hash of (model + messages content + tool names + temperature)
  - TTL: 5 minutes (configurable)
  - Max entries: 128
  - Only caches non-streaming calls (streaming is real-time)

Usage:
    from orca_code.response_cache import ResponseCache, get_response_cache

    cache = get_response_cache()
    cached = cache.get(model, messages, tools, temperature)
    if cached:
        return cached
    response = make_api_call(...)
    cache.set(model, messages, tools, temperature, response)
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any


class ResponseCache:
    """Thread-safe LRU cache for LLM API responses."""

    def __init__(self, max_size: int = 128, ttl_seconds: float = 300.0):
        self._max = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, model: str, messages: list[dict],
                  tools: list[dict] | None, temperature: float | None) -> str:
        """Create a deterministic cache key."""
        # Hash only the content, not the full structure
        msg_sig = json.dumps(
            [(m.get("role"), m.get("content", "")[:200]) for m in messages[-5:]],
            sort_keys=True, ensure_ascii=False,
        )
        tool_sig = json.dumps(
            [(t.get("function", {}).get("name", "")) for t in (tools or [])],
            sort_keys=True,
        )
        raw = f"{model}|{msg_sig}|{tool_sig}|{temperature}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def get(self, model: str, messages: list[dict],
            tools: list[dict] | None = None,
            temperature: float | None = None) -> Any | None:
        """Try to get a cached response. Returns None on miss/expiry."""
        key = self._make_key(model, messages, tools, temperature)
        with self._lock:
            if key not in self._store:
                self._misses += 1
                return None
            value, expires = self._store[key]
            if time.time() > expires:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, model: str, messages: list[dict],
            tools: list[dict] | None, temperature: float | None,
            response: Any):
        """Cache an API response."""
        key = self._make_key(model, messages, tools, temperature)
        expires = time.time() + self._ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (response, expires)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def clear(self):
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(total, 1), 3),
            }


_cache: ResponseCache | None = None


def get_response_cache() -> ResponseCache:
    global _cache
    if _cache is None:
        _cache = ResponseCache()
    return _cache
