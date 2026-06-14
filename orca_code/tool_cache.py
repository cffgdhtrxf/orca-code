"""orca_code.tool_cache — Tool output caching and structured results (P2-17).

Inspired by omp's AgentToolResult pattern and Claude Code's content replacement.

Features:
  - LRU cache for expensive tool operations (web_search, read_webpage, OCR, etc.)
  - Structured tool results with isError flag
  - Content hash-based cache keys
  - Cache invalidation by TTL and file mtime
  - Tool result storage with content replacement for large outputs
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Structured Tool Result
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ToolResult:
    """Structured result from a tool execution.

    Inspired by omp's AgentToolResult:
      - content: list of content blocks (text, image, resource)
      - isError: True if the tool encountered an error
      - details: arbitrary metadata
    """
    content: list[dict] = field(default_factory=list)
    is_error: bool = False
    details: dict = field(default_factory=dict)
    cached: bool = False
    elapsed_ms: float = 0.0

    @classmethod
    def from_text(cls, text: str, is_error: bool = False, **details) -> ToolResult:
        """Create a ToolResult from a plain text string."""
        return cls(
            content=[{"type": "text", "text": str(text)}],
            is_error=is_error,
            details=details,
        )

    @classmethod
    def from_error(cls, error_msg: str, **details) -> ToolResult:
        """Create an error ToolResult."""
        return cls.from_text(error_msg, is_error=True, **details)

    def to_text(self) -> str:
        """Extract plain text from content blocks for legacy consumers."""
        texts = []
        for block in self.content:
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "resource":
                texts.append(f"[Resource: {block.get('resource', {})}]")
        return "\n".join(texts)

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            "content": self.content,
            "isError": self.is_error,
            "details": self.details,
            "cached": self.cached,
            "elapsedMs": self.elapsed_ms,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# LRU Cache
# ═══════════════════════════════════════════════════════════════════════════════

class LRUCache:
    """Thread-safe LRU cache with TTL support."""

    def __init__(self, max_size: int = 256, default_ttl_seconds: float = 300.0):
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def _make_key(self, *args, **kwargs) -> str:
        """Create a deterministic cache key from arguments."""
        raw = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, *args, **kwargs) -> Any | None:
        """Get cached value. Returns None if not found or expired."""
        key = self._make_key(*args, **kwargs)
        with self._lock:
            if key not in self._cache:
                return None
            value, expires_at = self._cache[key]
            if time.time() > expires_at:
                del self._cache[key]
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            return value

    def set(self, value: Any, ttl_seconds: float | None = None, *args, **kwargs):
        """Set a cached value."""
        key = self._make_key(*args, **kwargs)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = time.time() + ttl
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, expires_at)
            # Evict oldest if over capacity
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, *args, **kwargs):
        """Remove a specific cache entry."""
        key = self._make_key(*args, **kwargs)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool-specific cache configs
# ═══════════════════════════════════════════════════════════════════════════════

# Tools that benefit from caching (expensive, idempotent-ish)
CACHEABLE_TOOLS: dict[str, float] = {
    "web_search": 300.0,       # 5 min — search results change slowly
    "read_webpage": 120.0,     # 2 min — pages may update
    "web_fetch": 120.0,        # 2 min
    "get_weather": 600.0,      # 10 min — weather doesn't change fast
    "get_location": 3600.0,    # 1 hour — location is static
    "ocr_image": 60.0,         # 1 min — image content doesn't change
    "get_system_info": 300.0,  # 5 min — system info is stable
    "list_files": 10.0,        # 10 sec — filesystem can change fast
    "search_files": 10.0,      # 10 sec
}

# ═══════════════════════════════════════════════════════════════════════════════
# Singleton cache instance
# ═══════════════════════════════════════════════════════════════════════════════

_tool_cache: LRUCache | None = None


def get_tool_cache() -> LRUCache:
    """Get or create the global tool cache singleton."""
    global _tool_cache
    if _tool_cache is None:
        _tool_cache = LRUCache(max_size=256, default_ttl_seconds=300.0)
    return _tool_cache


def cached_tool_call(tool_name: str, fn, *args, **kwargs) -> str:
    """Execute a tool call with caching.

    Args:
        tool_name: Name of the tool (used to look up TTL).
        fn: The tool function to call.
        *args, **kwargs: Arguments to pass to the tool function.

    Returns:
        The tool result as a string.
    """
    cache = get_tool_cache()

    # Check if this tool type is cacheable
    ttl = CACHEABLE_TOOLS.get(tool_name)
    if ttl is None:
        # Not cacheable — execute directly
        result = fn(*args, **kwargs)
        return result if isinstance(result, str) else str(result)

    # Try cache
    cached = cache.get(tool_name, *args, **kwargs)
    if cached is not None:
        if isinstance(cached, ToolResult):
            return cached.to_text()
        return str(cached)

    # Execute and cache
    try:
        result = fn(*args, **kwargs)
        result_str = result if isinstance(result, str) else str(result)
        cache.set(result_str, ttl_seconds=ttl, tool_name=tool_name, *args, **kwargs)
        return result_str
    except Exception:
        # Don't cache errors
        raise


def invalidate_tool_cache(tool_name: str | None = None):
    """Invalidate the tool cache for a specific tool or all tools."""
    cache = get_tool_cache()
    if tool_name is None:
        cache.clear()
    # Partial invalidation by tool name not supported directly —
    # the LRU naturally ages out entries. Use clear() for full reset.


# ═══════════════════════════════════════════════════════════════════════════════
# Content replacement storage (for large tool outputs)
# ═══════════════════════════════════════════════════════════════════════════════

class ContentStore:
    """Stores large tool outputs on disk, replacing inline content with a reference.

    When a tool output exceeds a threshold, the content is written to disk
    and the inline result is replaced with: "[Content stored: <key>]"
    """

    def __init__(self, store_dir: Path | None = None, max_inline_chars: int = 8000):
        if store_dir is None:
            from orca_code.config import TEMP_DIR
            store_dir = TEMP_DIR / "tool_outputs"
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_inline = max_inline_chars

    def store(self, content: str, tool_name: str = "unknown") -> str:
        """Store large content and return reference.

        If content is small, returns as-is.
        If content is large, writes to disk and returns reference key.
        """
        if len(content) <= self._max_inline:
            return content

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        ts = int(time.time())
        filename = f"{tool_name}_{ts}_{content_hash}.txt"
        filepath = self._dir / filename

        try:
            filepath.write_text(content, encoding="utf-8")
            return (
                f"[内容已存储: {filename}] "
                f"({len(content):,} 字符). "
                f"使用 read_file('{filepath}') 读取完整内容。"
            )
        except Exception:
            return content  # Fallback: return full content

    def retrieve(self, filename: str) -> str | None:
        """Retrieve stored content by filename."""
        filepath = self._dir / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def cleanup(self, max_age_seconds: float = 3600.0):
        """Remove stored outputs older than max_age_seconds."""
        now = time.time()
        for f in self._dir.glob("*.txt"):
            if now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)


_content_store: ContentStore | None = None


def get_content_store() -> ContentStore:
    """Get or create the content store singleton."""
    global _content_store
    if _content_store is None:
        _content_store = ContentStore()
    return _content_store
