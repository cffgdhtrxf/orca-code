"""orca_code.core.errors — Error classification and retry logic.

Inspired by Proma's error-patterns.ts: unified error categorization drives
automatic retry decisions, user-facing messages, and logging severity.

Categories:
  NETWORK     — transient, retryable (timeout, connection reset, DNS)
  AUTH        — permanent, not retryable (401, invalid key)
  RATE_LIMIT  — transient, retryable with backoff (429)
  MODEL       — permanent, not retryable (model not found, context too long)
  TOOL        — depends on tool (tool execution failures)
  PERMISSION  — not retryable (user denied permission)
  INTERNAL    — not retryable (unexpected internal errors)
"""

from __future__ import annotations

import re
import time
import logging
from enum import Enum
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ErrorCategory(Enum):
    """Unified error categories for classification and retry decisions."""
    NETWORK = "network"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    MODEL = "model"
    TOOL = "tool"
    PERMISSION = "permission"
    INTERNAL = "internal"


# ─── Error pattern matching ──────────────────────────────────────────────────

# Network error patterns (transient, retryable)
_NETWORK_PATTERNS: list[tuple[str, bool]] = [
    # (regex pattern, case_sensitive)
    (r"Connection (refused|reset|timed out|aborted)", False),
    (r"Network (is unreachable|error)", False),
    (r"Temporary failure in name resolution", False),
    (r"Could not resolve host", False),
    (r"SSL.*error", False),
    (r"timeout", False),
    (r"Too Many Requests", False),  # 429 HTTP
    (r"Service Unavailable", False),  # 503 HTTP
    (r"Bad Gateway", False),  # 502 HTTP
    (r"Gateway Timeout", False),  # 504 HTTP
    (r"ConnectionError", False),
    (r"RemoteDisconnected", False),
    (r"ProtocolError", False),
    (r"ReadTimeout", False),
    (r"ConnectTimeout", False),
]

# Auth error patterns (permanent, not retryable)
_AUTH_PATTERNS: list[tuple[str, bool]] = [
    (r"Invalid API Key", False),
    (r"Incorrect API key", False),
    (r"AuthenticationError", False),
    (r"401", False),
    (r"Unauthorized", False),
    (r"Forbidden", True),
    (r"403", False),
    (r"invalid.*auth", False),
    (r"auth.*failed", False),
]

# Rate limit patterns (transient, retryable with backoff)
_RATE_LIMIT_PATTERNS: list[tuple[str, bool]] = [
    (r"Rate limit", False),
    (r"rate_limit", True),
    (r"Too Many Requests", False),
    (r"429", False),
    (r"quota.*exceeded", False),
    (r"billing.*limit", False),
]

# Model error patterns (permanent)
_MODEL_PATTERNS: list[tuple[str, bool]] = [
    (r"model.*not found", False),
    (r"does not exist", False),
    (r"context.*length.*exceeded", False),
    (r"maximum context length", False),
    (r"token.*limit", False),
    (r"content_filter", False),
    (r"BadRequestError.*400", False),
    (r"invalid.*model", False),
]


def _match_any(message: str, patterns: list[tuple[str, bool]]) -> bool:
    """Check if message matches any pattern in the list."""
    flags = re.IGNORECASE
    for pattern, case_sensitive in patterns:
        flag = 0 if case_sensitive else re.IGNORECASE
        if re.search(pattern, message, flag):
            return True
    return False


def classify_error(error: Exception) -> tuple[ErrorCategory, bool]:
    """Classify an exception into a category and determine retryability.

    Args:
        error: The exception to classify.

    Returns:
        (ErrorCategory, is_retryable): Category and whether a retry is recommended.
    """
    message = str(error)

    # Check in priority order (most specific first)
    if _match_any(message, _AUTH_PATTERNS):
        return ErrorCategory.AUTH, False

    if _match_any(message, _RATE_LIMIT_PATTERNS):
        return ErrorCategory.RATE_LIMIT, True

    if _match_any(message, _MODEL_PATTERNS):
        return ErrorCategory.MODEL, False

    if _match_any(message, _NETWORK_PATTERNS):
        return ErrorCategory.NETWORK, True

    # Check error type hierarchy
    error_type = type(error).__name__

    # OpenAI/HTTP specific errors
    if "Authentication" in error_type:
        return ErrorCategory.AUTH, False
    if "RateLimit" in error_type:
        return ErrorCategory.RATE_LIMIT, True
    if "BadRequest" in error_type:
        return ErrorCategory.MODEL, False
    if "NotFound" in error_type:
        return ErrorCategory.MODEL, False
    if "Permission" in error_type or "PermissionError" in error_type:
        return ErrorCategory.PERMISSION, False

    # Default: treat unknown errors as internal, not retryable
    return ErrorCategory.INTERNAL, False


def friendly_error_message(error: Exception) -> str:
    """Convert an exception into a user-friendly error message.

    Maps technical errors to readable Chinese messages.
    """
    category, _ = classify_error(error)
    message = str(error)

    templates: dict[ErrorCategory, str] = {
        ErrorCategory.NETWORK: "网络连接失败，请检查网络后重试",
        ErrorCategory.AUTH: "API Key 无效，请在 config.json 中检查 api_key",
        ErrorCategory.RATE_LIMIT: "API 请求频率过高，请稍后重试",
        ErrorCategory.MODEL: f"模型错误: {message[:200]}",
        ErrorCategory.TOOL: f"工具执行失败: {message[:200]}",
        ErrorCategory.PERMISSION: f"权限不足: {message[:200]}",
        ErrorCategory.INTERNAL: f"内部错误: {message[:200]}",
    }

    return templates.get(category, f"未知错误: {message[:200]}")


def execute_with_retry(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute a function with intelligent retry based on error classification.

    Only retries on NETWORK and RATE_LIMIT errors. Other errors are re-raised
    immediately. Uses exponential backoff with jitter.

    Args:
        func: The function to execute.
        max_retries: Maximum number of retries (default 3).
        base_delay: Base delay in seconds for exponential backoff (default 2.0).
        max_delay: Maximum delay cap in seconds (default 30.0).
        *args: Positional arguments passed to func.
        **kwargs: Keyword arguments passed to func.

    Returns:
        The return value of func.

    Raises:
        The original exception if not retryable or max retries exhausted.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            category, retryable = classify_error(e)

            if not retryable or attempt >= max_retries:
                raise

            # Exponential backoff with jitter
            delay = min(base_delay * (2 ** attempt), max_delay)
            import random
            jitter = delay * 0.1 * random.random()
            wait = delay + jitter

            logger.warning(
                "Retry %d/%d after %.1fs: [%s] %s",
                attempt + 1, max_retries, wait, category.value,
                str(e)[:200],
            )
            time.sleep(wait)

    # Should never reach here, but satisfy type checker
    assert last_error is not None
    raise last_error
