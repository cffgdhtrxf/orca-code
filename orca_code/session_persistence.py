"""orca_code.session_persistence — JSONL-based session storage.

Replaces the legacy JSON full-read/full-write with append-only JSONL.
Each turn is written as one line. Crash-safe: the last line may be
incomplete, but all prior turns are intact.

Format:
    {"role":"user","content":"...","ts":"2026-06-08T12:00:00Z"}
    {"role":"assistant","content":"...","tool_calls":[...],"ts":"..."}
    {"role":"tool","tool_call_id":"...","content":"...","ts":"..."}

Benefits over JSON full-dump:
    - Atomic writes (one line at a time) → no corruption on crash
    - Append-only → O(1) per turn vs O(n) full file rewrite
    - Easily tail-able: `tail -f session.jsonl`
    - Compressible: line-level dedup for repeated content

Usage:
    from orca_code.session_persistence import JSONLSessionStore

    store = JSONLSessionStore("sessions/session_abc.jsonl")
    store.append("user", "What is the weather?")
    store.append("assistant", "It's sunny.", tool_calls=[])
    recent = store.tail(20)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from orca_code.utils import _sanitize_surrogates


class JSONLSessionStore:
    """Append-only JSONL session persistence.

    Thread-safe: writes are synchronized via a simple lock.
    """

    def __init__(self, file_path: Path):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write_count = 0

    # ── Write ────────────────────────────────────────────────────────────────

    def append(
        self,
        role: str,
        content: str,
        tool_calls: list[dict] | None = None,
        reasoning: str | None = None,
        tool_call_id: str | None = None,
    ) -> int:
        """Append one message as a JSONL line. Returns line number (1-based)."""
        record = {
            "role": role,
            "content": _sanitize_surrogates(str(content)[:50000]),  # Cap at 50K chars
            "ts": datetime.now(UTC).isoformat(),
        }
        if tool_calls:
            record["tool_calls"] = tool_calls
        if reasoning:
            record["reasoning"] = _sanitize_surrogates(str(reasoning)[:10000])
        if tool_call_id:
            record["tool_call_id"] = tool_call_id

        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(self._path, "a", encoding="utf-8", errors="replace") as f:
            f.write(line)
            self._write_count += 1

        return self._write_count

    def append_messages(self, messages: list[dict]) -> int:
        """Append multiple messages at once. Returns total lines written."""
        count = 0
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls")
            reasoning = msg.get("reasoning_content")
            tool_call_id = msg.get("tool_call_id")
            self.append(role, content, tool_calls, reasoning, tool_call_id)
            count += 1
        return count

    # ── Read ─────────────────────────────────────────────────────────────────

    def read_all(self) -> list[dict]:
        """Read all messages from the JSONL file. Returns list of dicts."""
        if not self._path.exists():
            return []
        messages = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip corrupted lines (crash recovery)
                    continue
        return messages

    def tail(self, n: int = 20) -> list[dict]:
        """Read the last n messages without loading the entire file.

        Uses a simple reverse-read buffer approach. For very large files
        (>100MB), consider using a separate index.
        """
        if not self._path.exists():
            return []
        if self._path.stat().st_size < 10 * 1024 * 1024:
            # Small file: just read everything and slice
            return self.read_all()[-n:]

        # Large file: read last ~8KB per expected line, up to a reasonable max
        chunk_size = min(n * 2048, 256 * 1024)  # 256KB max
        with open(self._path, "rb") as f:
            file_size = f.seek(0, 2)
            read_start = max(0, file_size - chunk_size)
            f.seek(read_start)
            raw = f.read().decode("utf-8", errors="replace")

        # Skip the first partial line
        lines = raw.split("\n")
        if read_start > 0 and lines:
            lines = lines[1:]  # First line might be partial

        messages = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return messages[-n:]

    def tail_as_messages(self, n: int = 20) -> list[dict]:
        """Return last n lines in OpenAI-compatible message format.

        Suitable for feeding directly into an LLM call as context.
        Skips system messages and tool results from the output.
        """
        records = self.tail(n)
        messages = []
        for r in records:
            role = r.get("role", "")
            if role == "system":
                continue
            msg = {"role": role, "content": r.get("content", "")}
            if r.get("tool_calls"):
                msg["tool_calls"] = r["tool_calls"]
            if r.get("tool_call_id"):
                msg["tool_call_id"] = r["tool_call_id"]
            messages.append(msg)
        return messages

    def count(self) -> int:
        """Count the number of lines in the file."""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path, encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count

    # ── Maintenance ──────────────────────────────────────────────────────────

    def compact(self, keep_last: int = 500) -> int:
        """Compact the file by keeping only the last N messages.

        Returns the number of messages removed.
        """
        if not self._path.exists():
            return 0
        all_msgs = self.read_all()
        if len(all_msgs) <= keep_last:
            return 0
        removed = len(all_msgs) - keep_last
        with open(self._path, "w", encoding="utf-8", errors="replace") as f:
            for msg in all_msgs[-keep_last:]:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return removed

    @property
    def path(self) -> Path:
        return self._path

    @property
    def size_bytes(self) -> int:
        if not self._path.exists():
            return 0
        return self._path.stat().st_size


# ═══════════════════════════════════════════════════════════════════════════════
# Session metadata (P2-15)
# ═══════════════════════════════════════════════════════════════════════════════

def save_session_metadata(
    session_id: str,
    metadata: dict,
    meta_dir: Path | None = None,
) -> None:
    """Save session metadata as a small JSON sidecar file.

    Stored alongside the JSONL file as <session_id>.meta.json
    """
    if meta_dir is None:
        from orca_code.config import SAVE_DIR
        meta_dir = SAVE_DIR
    meta_path = meta_dir / f"{session_id}.meta.json"
    try:
        meta_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_session_metadata(
    session_id: str,
    meta_dir: Path | None = None,
) -> dict:
    """Load session metadata from a JSON sidecar file."""
    if meta_dir is None:
        from orca_code.config import SAVE_DIR
        meta_dir = SAVE_DIR
    meta_path = meta_dir / f"{session_id}.meta.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_sessions(save_dir: Path | None = None) -> list[dict]:
    """List all saved sessions with metadata.

    Scans the save directory for .jsonl and .meta.json files.
    Returns list of {session_id, turns, size, created_at, model, description}.
    """
    if save_dir is None:
        from orca_code.config import SAVE_DIR
        save_dir = SAVE_DIR

    if not save_dir.exists():
        return []

    sessions: list[dict] = []
    seen_ids: set[str] = set()

    for jsonl_file in sorted(save_dir.glob("*.jsonl"), reverse=True):
        session_id = jsonl_file.stem
        if session_id in seen_ids:
            continue
        seen_ids.add(session_id)

        store = JSONLSessionStore(jsonl_file)
        meta = load_session_metadata(session_id, save_dir)

        sessions.append({
            "session_id": session_id,
            "turns": meta.get("turns", store.count() // 2),
            "message_count": store.count(),
            "size_bytes": jsonl_file.stat().st_size,
            "created_at": meta.get("created_at", ""),
            "model": meta.get("model", "unknown"),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
        })

    return sessions


def delete_session_files(
    session_id: str,
    save_dir: Path | None = None,
) -> bool:
    """Delete all files associated with a session.

    Removes: <id>.jsonl, <id>.meta.json
    Returns True if any files were deleted.
    """
    if save_dir is None:
        from orca_code.config import SAVE_DIR
        save_dir = SAVE_DIR

    deleted = False
    for pattern in [f"{session_id}.jsonl", f"{session_id}.meta.json"]:
        p = save_dir / pattern
        if p.exists():
            p.unlink()
            deleted = True
    return deleted


def search_sessions(query: str, save_dir: Path | None = None, limit: int = 10) -> list[dict]:
    """Full-text search across session files.

    Searches JSONL content for the query string.
    Returns matching session summaries with context snippets.
    """
    if save_dir is None:
        from orca_code.config import SAVE_DIR
        save_dir = SAVE_DIR

    if not save_dir.exists():
        return []

    results: list[dict] = []
    query_lower = query.lower()

    for jsonl_file in sorted(save_dir.glob("*.jsonl"), reverse=True):
        if len(results) >= limit:
            break

        try:
            content = jsonl_file.read_text(encoding="utf-8", errors="replace")
            if query_lower in content.lower():
                # Find context around first match
                idx = content.lower().find(query_lower)
                start = max(0, idx - 80)
                end = min(len(content), idx + len(query) + 80)
                snippet = content[start:end].replace("\n", " ").strip()

                results.append({
                    "session_id": jsonl_file.stem,
                    "snippet": f"...{snippet}..." if start > 0 else snippet + "...",
                    "size_bytes": jsonl_file.stat().st_size,
                })
        except Exception:
            continue

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Integration with session.py
# ═══════════════════════════════════════════════════════════════════════════════

def save_session_jsonl(session, store: JSONLSessionStore | None = None) -> int:
    """Save the current session to JSONL format.

    Args:
        session: The Session object from orca_code.session.
        store: Optional existing JSONLSessionStore. Created if None.

    Returns:
        Number of messages written.
    """
    if store is None:
        from orca_code.config import SAVE_DIR
        store = JSONLSessionStore(SAVE_DIR / "session.jsonl")

    return store.append_messages(session.messages)


def restore_session_jsonl(session, store: JSONLSessionStore | None = None) -> int:
    """Restore session messages from a JSONL file.

    Args:
        session: The Session object to populate.
        store: Optional existing JSONLSessionStore.

    Returns:
        Number of messages restored.
    """
    if store is None:
        from orca_code.config import SAVE_DIR
        store = JSONLSessionStore(SAVE_DIR / "session.jsonl")

    messages = store.read_all()
    if messages:
        # Filter: keep system message from current session if it exists
        current_system = None
        if session.messages and session.messages[0].get("role") == "system":
            current_system = session.messages[0]

        session.messages = messages
        if current_system:
            # Replace loaded system message with current one (may be newer)
            if session.messages and session.messages[0].get("role") == "system":
                session.messages[0] = current_system
            else:
                session.messages.insert(0, current_system)

    return len(messages)
