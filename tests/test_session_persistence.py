"""Tests for orca_code.session_persistence — JSONL session storage."""

import pytest

from orca_code.session_persistence import JSONLSessionStore


class TestJSONLSessionStore:
    """JSONL session store tests."""

    def test_append_and_read(self, tmp_path):
        """Append messages, then read them back."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        store.append("user", "Hello")
        store.append("assistant", "Hi there!")

        msgs = store.read_all()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello"
        assert msgs[1]["role"] == "assistant"
        assert "ts" in msgs[0]

    def test_empty_file(self, tmp_path):
        """Reading non-existent file returns empty list."""
        store = JSONLSessionStore(tmp_path / "nonexistent.jsonl")
        assert store.read_all() == []

    def test_tail(self, tmp_path):
        """tail() returns only the last N messages."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        for i in range(10):
            store.append("user", f"Message {i}")

        last3 = store.tail(3)
        assert len(last3) == 3
        assert last3[0]["content"] == "Message 7"
        assert last3[-1]["content"] == "Message 9"

    def test_tail_empty(self, tmp_path):
        """tail() on empty file returns empty list."""
        store = JSONLSessionStore(tmp_path / "empty.jsonl")
        assert store.tail(5) == []

    def test_count(self, tmp_path):
        """count() returns the correct number of lines."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        assert store.count() == 0
        store.append("user", "Hello")
        store.append("assistant", "World")
        assert store.count() == 2

    def test_append_with_tool_calls(self, tmp_path):
        """Append message with tool_calls field."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        store.append(
            "assistant", "Let me check",
            tool_calls=[{"name": "read_file", "args": {"path": "/test.txt"}}]
        )
        msgs = store.read_all()
        assert len(msgs) == 1
        assert "tool_calls" in msgs[0]
        assert msgs[0]["tool_calls"][0]["name"] == "read_file"

    def test_append_with_reasoning(self, tmp_path):
        """Append message with reasoning field."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        store.append("assistant", "Answer", reasoning="Deep thinking...")
        msgs = store.read_all()
        assert msgs[0]["reasoning"] == "Deep thinking..."

    def test_append_messages_bulk(self, tmp_path):
        """append_messages writes multiple messages at once."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        msgs = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]
        count = store.append_messages(msgs)
        assert count == 3
        assert store.count() == 3

    def test_compact(self, tmp_path):
        """compact() keeps only the last N messages."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        for i in range(100):
            store.append("user", f"Msg {i}")

        removed = store.compact(keep_last=20)
        assert removed == 80
        assert store.count() == 20
        msgs = store.read_all()
        assert msgs[0]["content"] == "Msg 80"

    def test_tail_as_messages(self, tmp_path):
        """tail_as_messages returns OpenAI-compatible format."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        store.append("system", "You are helpful.")
        store.append("user", "Hello")
        store.append("assistant", "Hi!")

        msgs = store.tail_as_messages(3)
        assert len(msgs) == 2  # System skipped
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_skips_corrupt_lines(self, tmp_path):
        """Corrupt JSON lines are silently skipped."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        store.append("user", "Good message")
        # Manually write a corrupt line
        with open(tmp_path / "test.jsonl", "a", encoding="utf-8") as f:
            f.write("this is not valid json\n")
        store.append("assistant", "Another good one")

        msgs = store.read_all()
        assert len(msgs) == 2  # Corrupt line skipped
        assert msgs[0]["content"] == "Good message"
        assert msgs[1]["content"] == "Another good one"

    def test_content_truncation(self, tmp_path):
        """Content is truncated to 50000 chars."""
        store = JSONLSessionStore(tmp_path / "test.jsonl")
        long_msg = "x" * 60000
        store.append("user", long_msg)
        msgs = store.read_all()
        assert len(msgs[0]["content"]) <= 50000


class TestSaveRestoreIntegration:
    """Tests for save_session_jsonl / restore_session_jsonl."""

    def test_save_restore_roundtrip(self, tmp_path):
        """Save and restore session messages."""
        from orca_code.session import Session
        from orca_code.session_persistence import restore_session_jsonl, save_session_jsonl

        session = Session()
        session.messages = [
            {"role": "system", "content": "You are a test bot."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]

        store = JSONLSessionStore(tmp_path / "session.jsonl")
        count = save_session_jsonl(session, store)
        assert count == 3

        # Create a new session and restore
        session2 = Session()
        session2.messages = [{"role": "system", "content": "New system prompt"}]

        restored = restore_session_jsonl(session2, store)
        assert restored == 3
        # System prompt should be preserved from session2
        assert session2.messages[0]["content"] == "New system prompt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
