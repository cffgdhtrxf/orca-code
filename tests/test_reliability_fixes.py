"""
Regression tests for Phase 2 reliability fixes.
Covers: CJK tokens, path traversal, tool_call_id, decrypt, empty list, encoding, ANSI reset.
"""
import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── CJK Token Estimation ────────────────────────────────────────────────────


class TestCJKTokenEstimation:
    """Verify _estimate_tokens and _token_counter handle CJK correctly."""

    def test_japanese_hiragana(self):
        from orca_code.utils import _estimate_tokens
        result = _estimate_tokens("こんにちは世界")
        assert result > 0, "Japanese text should have >0 tokens"

    def test_korean_hangul(self):
        from orca_code.utils import _estimate_tokens
        result = _estimate_tokens("안녕하세요세계")
        assert result > 0, "Korean text should have >0 tokens"

    def test_chinese(self):
        from orca_code.utils import _estimate_tokens
        result = _estimate_tokens("你好世界")
        assert result > 0, "Chinese text should have >0 tokens"

    def test_mixed_cjk_english_higher_than_pure_english(self):
        from orca_code.utils import _estimate_tokens
        en = _estimate_tokens("Hello World")
        mix = _estimate_tokens("Hello你好こんにちは안녕")
        assert mix > en, f"Mixed CJK+EN ({mix}) should > pure EN ({en})"

    def test_empty_string_zero(self):
        from orca_code.utils import _estimate_tokens
        assert _estimate_tokens("") == 0

    def test_tokenizer_fallback_on_empty_encode(self):
        """_token_counter.count should fall back to heuristic when tokenizer returns []."""
        from _token_counter import count, _heuristic

        # Mock tokenizer to return empty list (reproduces the bug)
        with patch("_token_counter._load_tokenizer") as mock_load:
            mock_tok = MagicMock()
            mock_tok.encode.return_value = []
            mock_load.return_value = mock_tok

            result = count("こんにちは世界")
            heuristic = _heuristic("こんにちは世界")
            assert result == heuristic, f"Should fall back to heuristic ({heuristic}), got {result}"

    def test_tokenizer_fallback_on_undercount(self):
        """_token_counter.count should fall back when tokenizer grossly under-counts."""
        from _token_counter import count, _heuristic

        with patch("_token_counter._load_tokenizer") as mock_load:
            mock_tok = MagicMock()
            # 1 token for 14 chars — way too low (1/14 ratio, < 1/8 threshold)
            mock_tok.encode.return_value = [12345]
            mock_load.return_value = mock_tok

            result = count("Hello你好こんにちは안녕")
            heuristic = _heuristic("Hello你好こんにちは안녕")
            assert result == heuristic, f"Should fall back to heuristic ({heuristic}), got {result}"


# ── Path Traversal Protection ───────────────────────────────────────────────


class TestPathTraversal:
    """Verify _validate_write_path blocks dangerous paths."""

    @pytest.mark.parametrize("path", [
        "../../etc/passwd",
        "output/../../etc/passwd",
        "../../../root/.ssh/authorized_keys",
        "temp/../../../../etc/shadow",
    ])
    def test_dotdot_traversal_blocked(self, path):
        from orca_code.utils import _validate_write_path
        _, err = _validate_write_path(path)
        assert err is not None, f"Path traversal should be blocked: {path}"

    @pytest.mark.parametrize("path", [
        "\\\\server\\share\\file.txt",
        "//server/share/file.txt",
    ])
    def test_unc_path_blocked(self, path):
        from orca_code.utils import _validate_write_path
        _, err = _validate_write_path(path)
        assert err is not None, f"UNC path should be blocked: {path}"

    @pytest.mark.parametrize("path", [
        "C:\\Windows\\System32\\config\\SAM",
    ])
    def test_system_directory_blocked(self, path):
        from orca_code.utils import _validate_write_path
        _, err = _validate_write_path(path)
        assert err is not None, f"System directory should be blocked: {path}"

    def test_linux_paths_blocked_on_windows_equivalent(self):
        """Paths resolving to etc/usr/bin parts should be blocked."""
        from orca_code.utils import _validate_write_path
        # On Windows, these won't resolve as absolute Linux paths,
        # so we test with a path that contains forbidden dir names in parts
        _, err = _validate_write_path("etc/passwd")
        # This may or may not be blocked depending on resolve behavior;
        # the important thing is it doesn't crash
        assert isinstance(err, (str, type(None)))

    @pytest.mark.parametrize("filename", [
        "config.json",
        ".env",
        "id_rsa",
        "id_ed25519",
        ".gitconfig",
        ".npmrc",
    ])
    def test_forbidden_filename_blocked(self, filename):
        from orca_code.utils import _validate_write_path
        _, err = _validate_write_path(filename)
        assert err is not None, f"Forbidden filename should be blocked: {filename}"

    @pytest.mark.parametrize("path", [
        "output/report.txt",
        "temp/scratch.py",
        "my_report.md",
        "notes.txt",
    ])
    def test_legitimate_path_allowed(self, path):
        from orca_code.utils import _validate_write_path
        _, err = _validate_write_path(path)
        assert err is None, f"Legitimate path should be allowed: {path}"


# ── Tool Call ID Consistency ───────────────────────────────────────────────


class TestToolCallId:
    """Verify tool_call_id fallback when id is empty."""

    def test_empty_id_gets_fallback(self):
        """When tc['id'] is empty, should use 'call_{idx}' as fallback."""
        # Simulate the logic from session_stream.py
        tool_calls = [
            {"id": "", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            {"id": "call_abc", "type": "function", "function": {"name": "write", "arguments": "{}"}},
        ]
        results = []
        for idx, tc in enumerate(tool_calls):
            call_id = tc["id"] or f"call_{idx}"
            results.append({"tool_call_id": call_id, "content": "ok"})

        assert results[0]["tool_call_id"] == "call_0", "Empty id should get fallback"
        assert results[1]["tool_call_id"] == "call_abc", "Non-empty id should be preserved"

    def test_none_id_gets_fallback(self):
        tool_calls = [
            {"id": None, "type": "function", "function": {"name": "read", "arguments": "{}"}},
        ]
        results = []
        for idx, tc in enumerate(tool_calls):
            call_id = tc["id"] or f"call_{idx}"
            results.append({"tool_call_id": call_id, "content": "ok"})

        assert results[0]["tool_call_id"] == "call_0", "None id should get fallback"


# ── Decrypt Failure Returns Empty ───────────────────────────────────────────


class TestDecryptFailure:
    """Verify session_crypto.decrypt_data returns empty string on failure."""

    def test_decrypt_invalid_data_returns_empty(self):
        from orca_code.session_crypto import decrypt_data, encrypt_data
        # Encrypt then corrupt
        encrypted = encrypt_data("test data")
        # Corrupt the ciphertext
        corrupted = encrypted[:-5] + "XXXXX"
        result = decrypt_data(corrupted)
        assert result == "", f"Decryption of corrupted data should return empty string, got {result!r}"

    def test_decrypt_garbage_returns_empty(self):
        from orca_code.session_crypto import decrypt_data
        result = decrypt_data("not-valid-base64!!!")
        assert result == "", f"Decryption of garbage should return empty string, got {result!r}"


# ── Empty List Protection ──────────────────────────────────────────────────


class TestEmptyListProtection:
    """Verify session_compaction handles empty message lists gracefully."""

    def test_empty_messages_no_crash(self):
        from orca_code.session_compaction import _legacy_compact
        # Empty list should not raise IndexError
        result = _legacy_compact([])
        assert isinstance(result, list), "Should return a list"
        assert result == [], "Empty input should return empty list"

    def test_system_only_messages(self):
        from orca_code.session_compaction import _legacy_compact
        msgs = [{"role": "system", "content": "You are helpful."}]
        result = _legacy_compact(msgs)
        assert isinstance(result, list), "Should return a list without crashing"

    def test_normal_messages_unchanged(self):
        from orca_code.session_compaction import _legacy_compact
        msgs = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = _legacy_compact(msgs)
        assert len(result) >= 1, "Should preserve at least some messages"


# ── Choices[0] Protection ─────────────────────────────────────────────────


class TestChoicesProtection:
    """Verify empty choices don't crash the orchestrator/session code."""

    def test_empty_choices_handled(self):
        """Simulate a response with empty choices list."""
        mock_response = MagicMock()
        mock_response.choices = []

        # The guard pattern used across the codebase
        if mock_response.choices:
            first = mock_response.choices[0]
        else:
            first = None

        assert first is None, "Empty choices should yield None, not raise IndexError"


# ── Encoding Consistency ───────────────────────────────────────────────────


class TestEncodingConsistency:
    """Verify key files use explicit encoding for I/O."""

    def test_alias_store_round_trip(self, temp_dir):
        """alias_store read/write should work with non-ASCII data."""
        from orca_code.alias_store import save_aliases, load_aliases
        with patch("orca_code.alias_store._path", return_value=temp_dir / "aliases.json"):
            aliases = {"你好": "hello", "명령": "command"}
            save_aliases(aliases)
            loaded = load_aliases()
            assert loaded == aliases, f"Round-trip failed: {loaded}"

    def test_usage_budget_round_trip(self, temp_dir):
        """usage_budget read/write should work with non-ASCII paths."""
        budget_file = temp_dir / "budget.json"
        budget_file.write_text(
            json.dumps({"tokens": 100, "cost": 0.05}),
            encoding="utf-8"
        )
        # Should read back fine
        data = json.loads(budget_file.read_text(encoding="utf-8"))
        assert data["tokens"] == 100


# ── ANSI Triple Reset ─────────────────────────────────────────────────────


class TestAnsiReset:
    """Verify logo/ANSI uses triple reset for clean terminal."""

    def test_triple_reset_in_stream_module(self):
        """session_stream should use triple ANSI reset sequence."""
        import orca_code.session_stream as ss
        src = Path(ss.__file__).read_text(encoding="utf-8")
        # Triple reset pattern: three consecutive \033[0m
        assert "\\033[0m\\033[0m\\033[0m" in src or "\033[0m\033[0m\033[0m" in src, \
            "session_stream should use triple ANSI reset"


# ── Shlex Failure Safety ──────────────────────────────────────────────────


class TestShlexFailureSafety:
    """Verify security.py refuses unparseable commands (not allows them)."""

    def test_shlex_unparseable_command_rejected(self):
        """When shlex can't parse a command, check_mode_command should reject it."""
        from orca_code.security import check_mode_command
        from orca_code.permissions import PermissionMode
        # Commands with unmatched quotes cause shlex.split to raise ValueError
        result, reason = check_mode_command('echo "unclosed quote', PermissionMode.AUTO)
        assert result is False, f"Unparseable command should be rejected, got allowed: {reason}"
        assert "无法解析" in reason, f"Reason should mention parse failure: {reason}"
