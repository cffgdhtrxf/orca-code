"""
memory_manager.py — Unified memory system for Orca Code.
Stores complete conversation turns in SQLite + FTS5 for permanent retrieval.
Rolling summary persisted in meta table for cross-session context injection.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class MemoryManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-8000")  # 8MB cache
        self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._has_fts = True
        self._init_db()

    # ----------------------------------------------------------------
    # Schema
    # ----------------------------------------------------------------
    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS turns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                role        TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
            CREATE INDEX IF NOT EXISTS idx_turns_session_turn ON turns(session_id, turn_number);

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # FTS5 may not be available in some Python builds
        try:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                    content, tokenize='unicode61',
                    content='turns', content_rowid='id'
                );
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS turns_fts_insert AFTER INSERT ON turns BEGIN
                    INSERT INTO turns_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS turns_fts_delete AFTER DELETE ON turns BEGIN
                    INSERT INTO turns_fts(turns_fts, rowid, content) VALUES ('delete', old.id, old.content);
                END;
            """)
        except Exception:
            self._has_fts = False
        self._conn.commit()

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------
    @staticmethod
    def _escape_fts5(query: str) -> str:
        """Escape FTS5 special characters and wrap for safe exact phrase match."""
        # Double-quote escaping prevents FTS5 syntax injection (AND, OR, NOT, *, etc.)
        escaped = query.replace('"', '""')
        return f'"{escaped}"'

    def save_message(self, session_id: str, turn_number: int,
                     role: str, content: str) -> int:
        """Store a single message. Content truncated at 10000 chars."""
        self._conn.execute(
            "INSERT INTO turns (session_id, turn_number, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, turn_number, role, str(content)[:10000],
             datetime.now().isoformat())
        )
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def search(self, query: str, limit: int = 5,
               session_id: Optional[str] = None) -> List[Dict]:
        """Dual search: FTS5 for English keywords + LIKE for Chinese. Deduplicated."""
        limit = min(max(1, limit), 20)
        seen = set()
        results = []

        # Pass 1: FTS5 (handles English keywords well)
        if self._has_fts:
            try:
                sql = (
                    "SELECT t.id, t.session_id, t.turn_number, t.role, t.content, t.timestamp "
                    "FROM turns_fts f JOIN turns t ON f.rowid = t.id "
                    "WHERE turns_fts MATCH ?"
                )
                params = [self._escape_fts5(query)]
                if session_id:
                    sql += " AND t.session_id = ?"
                    params.append(session_id)
                sql += " ORDER BY t.id DESC LIMIT ?"
                params.append(limit)
                for r in self._conn.execute(sql, params).fetchall():
                    if r[0] not in seen:
                        seen.add(r[0])
                        results.append(
                            {"id": r[0], "session_id": r[1], "turn_number": r[2],
                             "role": r[3], "content": r[4], "timestamp": r[5]}
                        )
            except Exception:
                pass

        # Pass 2: LIKE fallback (handles Chinese, fills gaps)
        if len(results) < limit:
            sql = (
                "SELECT id, session_id, turn_number, role, content, timestamp "
                "FROM turns WHERE content LIKE ?"
            )
            params = [f'%{query}%']
            if session_id:
                sql += " AND session_id = ?"
                params.append(session_id)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            for r in self._conn.execute(sql, params).fetchall():
                if r[0] not in seen:
                    seen.add(r[0])
                    results.append(
                        {"id": r[0], "session_id": r[1], "turn_number": r[2],
                         "role": r[3], "content": r[4], "timestamp": r[5]}
                    )

        # Pass 3: character-level LIKE — split into chars + space-separated words
        if len(results) < limit:
            words = [w for w in query.split() if len(w) >= 2]
            chars = [c for c in query if c.strip() and '一' <= c <= '鿿']
            terms = words + chars
            seen_terms = set()
            for term in terms:
                if term in seen_terms:
                    continue
                seen_terms.add(term)
                sql2 = (
                    "SELECT id, session_id, turn_number, role, content, timestamp "
                    "FROM turns WHERE content LIKE ? "
                    "ORDER BY id DESC LIMIT ?"
                )
                for r in self._conn.execute(sql2, [f'%{term}%', limit]).fetchall():
                    if r[0] not in seen:
                        seen.add(r[0])
                        results.append(
                            {"id": r[0], "session_id": r[1], "turn_number": r[2],
                             "role": r[3], "content": r[4], "timestamp": r[5]}
                        )

        return results[:limit]

    def search_with_snippet(self, query: str, limit: int = 5,
                            snippet_chars: int = 150) -> List[Dict]:
        """Dual search returning snippets (FTS5 highlight) or truncated content (LIKE)."""
        limit = min(max(1, limit), 20)
        seen = set()
        results = []

        # Pass 1: FTS5 with snippet() for keyword highlighting
        if self._has_fts:
            try:
                sql = (
                    "SELECT t.id, t.session_id, t.turn_number, t.role, t.content, t.timestamp, "
                    f"snippet(turns_fts, 1, '**', '**', '...', {snippet_chars}) AS snip "
                    "FROM turns_fts f JOIN turns t ON f.rowid = t.id "
                    "WHERE turns_fts MATCH ? "
                    "ORDER BY t.id DESC LIMIT ?"
                )
                for r in self._conn.execute(sql, [self._escape_fts5(query), limit]).fetchall():
                    if r[0] not in seen:
                        seen.add(r[0])
                        results.append(
                            {"id": r[0], "session_id": r[1], "turn_number": r[2],
                             "role": r[3], "content": r[4], "timestamp": r[5],
                             "snippet": r[6] or r[4][:300]}
                        )
            except Exception:
                pass

        # Pass 2: LIKE for Chinese / fallback
        if len(results) < limit:
            sql = (
                "SELECT id, session_id, turn_number, role, content, timestamp "
                "FROM turns WHERE content LIKE ? "
                "ORDER BY id DESC LIMIT ?"
            )
            for r in self._conn.execute(sql, [f'%{query}%', limit]).fetchall():
                if r[0] not in seen:
                    seen.add(r[0])
                    results.append(
                        {"id": r[0], "session_id": r[1], "turn_number": r[2],
                         "role": r[3], "content": r[4], "timestamp": r[5],
                         "snippet": r[4][:300]}
                    )

        # Pass 3: character-level LIKE — split into chars + space-separated words
        if len(results) < limit:
            words = [w for w in query.split() if len(w) >= 2]
            chars = [c for c in query if c.strip() and '一' <= c <= '鿿']
            terms = words + chars
            seen_terms = set()
            for term in terms:
                if term in seen_terms:
                    continue
                seen_terms.add(term)
                sql2 = (
                    "SELECT id, session_id, turn_number, role, content, timestamp "
                    "FROM turns WHERE content LIKE ? "
                    "ORDER BY id DESC LIMIT ?"
                )
                for r in self._conn.execute(sql2, [f'%{term}%', limit]).fetchall():
                    if r[0] not in seen:
                        seen.add(r[0])
                        results.append(
                            {"id": r[0], "session_id": r[1], "turn_number": r[2],
                             "role": r[3], "content": r[4], "timestamp": r[5]}
                        )

        return results[:limit]

    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", [key]
        ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [key, value]
        )
        self._conn.commit()

    def get_recent_turns(self, limit: int = 20) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT id, session_id, turn_number, role, content, timestamp "
            "FROM turns ORDER BY id DESC LIMIT ?", [limit]
        ).fetchall()
        return [
            {"id": r[0], "session_id": r[1], "turn_number": r[2],
             "role": r[3], "content": r[4], "timestamp": r[5]}
            for r in rows
        ]

    def get_memory_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM turns").fetchone()
        return row[0] if row else 0

    def clear_all(self) -> int:
        count = self.get_memory_count()
        self._conn.execute("DELETE FROM turns")
        self._conn.execute("DELETE FROM meta")
        self._conn.commit()
        return count

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
