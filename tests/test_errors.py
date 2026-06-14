"""Tests for core/errors.py — error classification and retry logic."""

import pytest

from orca_code.core.errors import (
    ErrorCategory,
    classify_error,
    execute_with_retry,
    friendly_error_message,
)


class TestErrorClassification:
    """Verify error classification works for all categories."""

    def test_classify_network_timeout(self):
        cat, retry = classify_error(Exception("Connection timed out"))
        assert cat == ErrorCategory.NETWORK
        assert retry is True

    def test_classify_connection_refused(self):
        cat, retry = classify_error(Exception("Connection refused by remote host"))
        assert cat == ErrorCategory.NETWORK
        assert retry is True

    def test_classify_auth_invalid_key(self):
        cat, retry = classify_error(Exception("Invalid API Key provided"))
        assert cat == ErrorCategory.AUTH
        assert retry is False

    def test_classify_auth_401(self):
        cat, retry = classify_error(Exception("HTTP 401 Unauthorized"))
        assert cat == ErrorCategory.AUTH
        assert retry is False

    def test_classify_rate_limit(self):
        cat, retry = classify_error(Exception("Rate limit exceeded. Try again later."))
        assert cat == ErrorCategory.RATE_LIMIT
        assert retry is True

    def test_classify_rate_limit_429(self):
        cat, retry = classify_error(Exception("HTTP 429 Too Many Requests"))
        assert cat == ErrorCategory.RATE_LIMIT
        assert retry is True

    def test_classify_model_not_found(self):
        cat, retry = classify_error(Exception("The model `gpt-999` does not exist"))
        assert cat == ErrorCategory.MODEL
        assert retry is False

    def test_classify_context_too_long(self):
        cat, retry = classify_error(Exception("context length exceeded maximum context length of 128000"))
        assert cat == ErrorCategory.MODEL
        assert retry is False

    def test_classify_permission_denied(self):
        cat, retry = classify_error(PermissionError("Permission denied: /etc/shadow"))
        assert cat == ErrorCategory.PERMISSION
        assert retry is False

    def test_classify_unknown_error(self):
        cat, retry = classify_error(Exception("Some random unexpected error"))
        assert cat == ErrorCategory.INTERNAL
        assert retry is False


class TestFriendlyMessages:
    """Verify friendly error messages are user-readable."""

    def test_network_message(self):
        msg = friendly_error_message(Exception("Connection timed out"))
        assert "网络" in msg  # Chinese message

    def test_auth_message(self):
        msg = friendly_error_message(Exception("Invalid API Key"))
        assert "API Key" in msg

    def test_model_message_preserves_detail(self):
        msg = friendly_error_message(Exception("model deepseek-v5 not found"))
        assert "deepseek-v5" in msg


class TestRetryLogic:
    """Verify execute_with_retry behavior."""

    def test_retry_on_network_error(self):
        call_count = [0]

        def flaky_func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Connection timed out")
            return "success"

        result = execute_with_retry(flaky_func, max_retries=3)
        assert result == "success"
        assert call_count[0] == 3

    def test_no_retry_on_auth_error(self):
        call_count = [0]

        def auth_fail():
            call_count[0] += 1
            raise Exception("Invalid API Key")

        with pytest.raises(Exception, match="Invalid API Key"):
            execute_with_retry(auth_fail, max_retries=3)
        assert call_count[0] == 1  # Should NOT retry

    def test_successful_first_try(self):
        result = execute_with_retry(lambda: "ok", max_retries=3)
        assert result == "ok"

    def test_exhausts_retries(self):
        call_count = [0]

        def always_fails():
            call_count[0] += 1
            raise ConnectionError("Connection timed out")

        with pytest.raises(ConnectionError):
            execute_with_retry(always_fails, max_retries=2)
        assert call_count[0] == 3  # 1 initial + 2 retries
