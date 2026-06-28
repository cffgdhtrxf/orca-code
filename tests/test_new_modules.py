"""tests.test_new_modules — Tests for new modules added in v5.3.

Tests: tool_validator, rollback, workspace_detect, config_validator,
        compaction, fallback, tool_cache, rate_tracker, hooks.
"""

from __future__ import annotations

import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Tool Validator
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolValidator:
    def test_missing_required(self):
        from orca_code.tool_validator import validate_tool_args
        errors = validate_tool_args("read_file", {})
        assert len(errors) > 0
        assert any("path" in e for e in errors)

    def test_valid_args(self):
        from orca_code.tool_validator import validate_tool_args
        errors = validate_tool_args("read_file", {"path": "/tmp/test.txt"})
        assert len(errors) == 0

    def test_invalid_type(self):
        from orca_code.tool_validator import validate_tool_args
        errors = validate_tool_args("gui_click", {"x": "not_a_number", "y": 100})
        assert len(errors) > 0

    def test_enum_values(self):
        from orca_code.tool_validator import validate_tool_args
        errors = validate_tool_args("gui_click", {"x": 10, "y": 20, "button": "middle"})
        assert len(errors) == 0
        errors2 = validate_tool_args("gui_click", {"x": 10, "y": 20, "button": "invalid"})
        assert len(errors2) > 0

    def test_validate_with_suggestion(self):
        from orca_code.tool_validator import validate_with_suggestion
        err = validate_with_suggestion("read_file", {})
        assert err is not None
        assert "path" in err
        ok = validate_with_suggestion("read_file", {"path": "/tmp"})
        assert ok is None


# ═══════════════════════════════════════════════════════════════════════════════
# Config Validator
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigValidator:
    def test_valid_config(self):
        from orca_code.config_validator import validate_config
        result = validate_config({
            "api_key": "sk-test123", "base_url": "https://api.test.com/v1",
            "model_name": "test-model", "max_output_tokens": 4096,
            "context_max_tokens": 32000,
        })
        assert result.error_count == 0

    def test_missing_required(self):
        from orca_code.config_validator import validate_config
        result = validate_config({})
        assert result.error_count >= 4  # api_key, base_url, model_name, max_output_tokens, context_max_tokens

    def test_invalid_url(self):
        from orca_code.config_validator import validate_config
        result = validate_config({
            "api_key": "sk-test", "base_url": "not-a-valid-url",
            "model_name": "test", "max_output_tokens": 4096,
            "context_max_tokens": 32000,
        })
        assert any("URL" in i.message for i in result.issues)

    def test_range_check(self):
        from orca_code.config_validator import validate_config
        result = validate_config({
            "api_key": "sk-test", "base_url": "https://api.test.com/v1",
            "model_name": "test", "max_output_tokens": 0,  # below min
            "context_max_tokens": 32000,
        })
        assert any("太小" in i.message or "小" in i.message for i in result.issues)

    def test_not_dict(self):
        from orca_code.config_validator import validate_config
        result = validate_config("not a dict")
        assert result.error_count > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Rollback / File Tracker
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileTracker:
    def test_empty_tracker(self):
        from orca_code.rollback import FileTracker
        ft = FileTracker()
        assert ft.pending_count == 0
        result = ft.undo_last()
        assert "没有" in result

    def test_record_and_undo(self, tmp_path: Path):
        from orca_code.rollback import FileTracker
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        ft = FileTracker(snapshot_dir=tmp_path / "snapshots")
        snapshot = ft.snapshot(str(test_file))
        assert snapshot is not None
        assert Path(snapshot).exists()

        # Modify the file
        test_file.write_text("modified content")
        ft.record_change(str(test_file), "edit_file", snapshot)

        assert ft.pending_count == 1

        # Undo
        result = ft.undo_last()
        assert "已回滚" in result or "回滚" in result
        assert test_file.read_text() == "original content"
        assert ft.pending_count == 0

    def test_format_changes(self, tmp_path: Path):
        from orca_code.rollback import FileTracker
        ft = FileTracker(snapshot_dir=tmp_path / "snapshots")
        test_file = tmp_path / "test2.txt"
        test_file.write_text("hello")
        snap = ft.snapshot(str(test_file))
        ft.record_change(str(test_file), "write_file", snap)
        formatted = ft.format_changes()
        assert "test2.txt" in formatted


# ═══════════════════════════════════════════════════════════════════════════════
# Compaction
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompaction:
    def test_no_compaction_needed(self):
        from orca_code.session_compaction import compact_messages
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = compact_messages(msgs)
        assert len(result) == len(msgs)  # Under threshold, unchanged

    def test_compaction_preserves_system(self):
        from orca_code.session_compaction import compact_messages
        msgs = [
            {"role": "system", "content": "System prompt"},
        ]
        # Add many turns
        for i in range(30):
            msgs.append({"role": "user", "content": f"Question {i}"})
            msgs.append({"role": "assistant", "content": f"Answer {i}"})
        result = compact_messages(msgs)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "System prompt"


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallback:
    def test_is_retryable(self):
        from orca_code.fallback import is_retryable_error
        assert is_retryable_error(Exception("HTTP 429"))
        assert is_retryable_error(Exception("timeout"))
        assert is_retryable_error(Exception("HTTP 503"))
        assert not is_retryable_error(Exception("HTTP 401"))
        assert not is_retryable_error(Exception("HTTP 403"))

    def test_circuit_breaker_opens(self):
        from orca_code.fallback import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
        assert not cb.is_open("test_tool")
        cb.record_failure("test_tool")
        assert not cb.is_open("test_tool")
        cb.record_failure("test_tool")
        assert cb.is_open("test_tool")
        cb.record_success("test_tool")
        assert not cb.is_open("test_tool")


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Cache
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolCache:
    def test_lru_cache(self):
        from orca_code.tool_cache import LRUCache
        cache = LRUCache(max_size=3, default_ttl_seconds=60)
        cache.set("value1", ttl_seconds=60, key1="a")
        assert cache.get(key1="a") == "value1"
        assert cache.get(key1="b") is None

    def test_cache_expiry(self):
        from orca_code.tool_cache import LRUCache
        cache = LRUCache(max_size=3, default_ttl_seconds=0.01)
        cache.set("value", ttl_seconds=0.01, key="x")
        time.sleep(0.02)
        assert cache.get(key="x") is None

    def test_tool_result(self):
        from orca_code.tool_cache import ToolResult
        tr = ToolResult.from_text("hello", is_error=False)
        assert tr.to_text() == "hello"
        assert not tr.is_error

        err_tr = ToolResult.from_error("something went wrong")
        assert err_tr.is_error
        assert "something went wrong" in err_tr.to_text()


# ═══════════════════════════════════════════════════════════════════════════════
# Rate Tracker
# ═══════════════════════════════════════════════════════════════════════════════

class TestRateTracker:
    def test_record_and_stats(self):
        from orca_code.rate_tracker import RateTracker
        rt = RateTracker(window_seconds=60)
        rt.record_call(input_tokens=100, output_tokens=50)
        rt.record_call(input_tokens=200, output_tokens=100)
        stats = rt.get_total_stats()
        assert stats["total_calls"] == 2
        assert stats["total_input_tokens"] == 300
        assert stats["total_output_tokens"] == 150

    def test_window_stats(self):
        from orca_code.rate_tracker import RateTracker
        rt = RateTracker(window_seconds=60)
        rt.record_call(input_tokens=500, output_tokens=200)
        w = rt.get_window_stats()
        assert w["calls_per_minute"] == 1
        assert w["total_tokens_per_minute"] == 700


# ═══════════════════════════════════════════════════════════════════════════════
# Hooks
# ═══════════════════════════════════════════════════════════════════════════════

class TestHooks:
    def test_register_and_run(self):
        from orca_code.hooks import HookContext, HookRegistry
        reg = HookRegistry()

        calls = []
        def my_hook(ctx: HookContext) -> dict | None:
            calls.append(ctx.tool_name)
            return None

        reg.register_pre("test_tool", my_hook)
        ctx = HookContext(tool_name="test_tool", args={})
        allowed, _ = reg.run_pre_hooks(ctx)
        assert allowed
        assert len(calls) == 1
        assert calls[0] == "test_tool"

    def test_wildcard_hook(self):
        from orca_code.hooks import HookContext, HookRegistry
        reg = HookRegistry()

        count = []
        def counter(ctx):
            count.append(1)
            return None

        reg.register_pre("*", counter)
        reg.run_pre_hooks(HookContext(tool_name="tool_a", args={}))
        reg.run_pre_hooks(HookContext(tool_name="tool_b", args={}))
        assert len(count) == 2

    def test_post_hook_transform(self):
        from orca_code.hooks import HookContext, HookRegistry
        reg = HookRegistry()

        def upper(ctx, result):
            return result.upper()

        reg.register_post("echo", upper)
        result = reg.run_post_hooks(
            HookContext(tool_name="echo", args={}), "hello"
        )
        assert result == "HELLO"


# ═══════════════════════════════════════════════════════════════════════════════
# Workspace Detection
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkspaceDetect:
    def test_detect_python(self):
        from orca_code.workspace_detect import detect_workspace
        # The test itself runs from the project, so it should detect Python
        ws = detect_workspace()
        assert ws.language != "unknown" or ws.has_project

    def test_get_context(self):
        from orca_code.workspace_detect import get_workspace_context
        ctx = get_workspace_context()
        assert isinstance(ctx, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Shell Session
# ═══════════════════════════════════════════════════════════════════════════════

class TestShellSession:
    def test_oneshot_fallback(self):
        from orca_code.shell_session import ShellSession
        shell = ShellSession(session_id="test")
        # Don't start the persistent session — test oneshot fallback
        result = shell._run_oneshot("echo hello", timeout=5)
        assert "hello" in result.lower()

    def test_session_creation(self):
        from orca_code.shell_session import ShellSession
        shell = ShellSession(session_id="test2")
        assert shell.session_id == "test2"
        assert not shell.is_running
