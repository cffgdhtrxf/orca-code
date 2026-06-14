"""orca_code.memory.knowledge_graph — Entity-Relation knowledge graph.

Beyond keyword search — understands:
  - Entities: files, people, projects, APIs, errors, concepts
  - Relations: depends_on, fixes, belongs_to, similar_to, uses
  - Temporal: when learned, last accessed, confidence decay
  - Graph traversal: BFS neighbors up to N hops

Storage: SQLite with FTS5 + JSON1 extensions.
Query: graph traversal + FTS5 hybrid search.

Usage:
    from orca_code.memory import KnowledgeGraph

    kg = KnowledgeGraph(":memory:")  # or Path to SQLite file
    kg.add_entity("file:main.py", "file", "main.py", {"language": "python"})
    kg.relate("file:main.py", "imports", "file:utils.py")
    results = kg.query("main.py", depth=2)
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class KnowledgeGraph:
    """Semantic memory as entity-relation graph.

    Entities represent things the agent has learned about.
    Relations connect entities with typed edges.
    FTS5 enables full-text search across entity labels and metadata.
    """

    def __init__(self, db_path: str | Path):
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.row_factory = sqlite3.Row
        self._has_fts = True
        self._init_schema()

    # ── Schema ──────────────────────────────────────────────────────────────

    def _init_schema(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                label       TEXT NOT NULL,
                metadata    TEXT DEFAULT '{}',
                created_at  TEXT DEFAULT (datetime('now')),
                last_accessed_at TEXT,
                access_count INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

            CREATE TABLE IF NOT EXISTS relations (
                source_id   TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                relation    TEXT NOT NULL,
                target_id   TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                confidence  REAL DEFAULT 0.5,
                source_type TEXT DEFAULT 'observed',
                created_at  TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (source_id, relation, target_id)
            );

            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
        """)

        # FTS5 for entity search
        try:
            self._db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
                    label, metadata, content='entities', content_rowid='rowid'
                );
            """)
        except Exception:
            self._has_fts = False

        self._db.commit()

    # ── Entity CRUD ─────────────────────────────────────────────────────────

    def add_entity(
        self,
        entity_id: str,
        entity_type: str,
        label: str,
        metadata: dict | None = None,
    ):
        """Add or update an entity."""
        now = datetime.now(UTC).isoformat()
        self._db.execute(
            """INSERT OR REPLACE INTO entities (id, type, label, metadata, last_accessed_at, access_count)
               VALUES (?, ?, ?, ?, ?,
                 COALESCE((SELECT access_count FROM entities WHERE id = ?), 0) + 1)""",
            (entity_id, entity_type, label, json.dumps(metadata or {}, ensure_ascii=False), now, entity_id),
        )
        self._db.commit()

    def get_entity(self, entity_id: str) -> dict | None:
        """Get an entity by ID. Updates access timestamp."""
        row = self._db.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            return None
        # Update access
        self._db.execute(
            "UPDATE entities SET last_accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
            (datetime.now(UTC).isoformat(), entity_id),
        )
        self._db.commit()
        return dict(row)

    def find_entities(
        self,
        entity_type: str | None = None,
        label_contains: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Find entities by type and/or label substring."""
        conditions = []
        params: list = []

        if entity_type:
            conditions.append("type = ?")
            params.append(entity_type)
        if label_contains:
            conditions.append("label LIKE ?")
            params.append(f"%{label_contains}%")

        sql = "SELECT * FROM entities"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY access_count DESC LIMIT ?"
        params.append(limit)

        return [dict(row) for row in self._db.execute(sql, params).fetchall()]

    def delete_entity(self, entity_id: str):
        """Delete an entity and all its relations."""
        self._db.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        self._db.commit()

    @property
    def entity_count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) FROM entities").fetchone()
        return row[0] if row else 0

    # ── Relations ───────────────────────────────────────────────────────────

    def relate(
        self,
        source: str,
        relation: str,
        target: str,
        confidence: float = 0.5,
        source_type: str = "observed",
    ):
        """Create or update a relationship between two entities.

        Auto-creates entities if they don't exist.
        """
        # Ensure both entities exist
        for eid in (source, target):
            existing = self._db.execute(
                "SELECT id FROM entities WHERE id = ?", (eid,)
            ).fetchone()
            if not existing:
                self.add_entity(
                    eid, "unknown", eid.split(":")[-1] if ":" in eid else eid
                )

        self._db.execute(
            """INSERT OR REPLACE INTO relations (source_id, relation, target_id, confidence, source_type)
               VALUES (?, ?, ?, ?, ?)""",
            (source, relation, target, confidence, source_type),
        )
        self._db.commit()

    def get_relations(
        self,
        entity_id: str,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[dict]:
        """Get relations for an entity.

        Args:
            entity_id: The entity to query.
            direction: "outgoing", "incoming", or "both".
            relation_type: Optional filter by relation name.
        """
        results = []

        if direction in ("outgoing", "both"):
            sql = "SELECT * FROM relations WHERE source_id = ?"
            params: list = [entity_id]
            if relation_type:
                sql += " AND relation = ?"
                params.append(relation_type)
            results.extend(dict(r) for r in self._db.execute(sql, params).fetchall())

        if direction in ("incoming", "both"):
            sql = "SELECT * FROM relations WHERE target_id = ?"
            params = [entity_id]
            if relation_type:
                sql += " AND relation = ?"
                params.append(relation_type)
            results.extend(dict(r) for r in self._db.execute(sql, params).fetchall())

        return results

    def delete_relation(self, source: str, relation: str, target: str):
        """Delete a specific relation."""
        self._db.execute(
            "DELETE FROM relations WHERE source_id = ? AND relation = ? AND target_id = ?",
            (source, relation, target),
        )
        self._db.commit()

    # ── Graph Traversal ─────────────────────────────────────────────────────

    def query(self, entity_label: str, depth: int = 2, limit: int = 50) -> dict:
        """Traverse the graph from entities matching a label.

        Uses BFS via recursive CTE up to `depth` hops.

        Args:
            entity_label: Label substring to search for (LIKE match).
            depth: Max hops from matched entities.
            limit: Max nodes to return.

        Returns:
            Dict with root entity info + list of neighbor nodes.
        """
        # Find matching entities first (FTS5 or LIKE)
        matched = self.search_entities(entity_label, limit=5)
        if not matched:
            return {"root": entity_label, "depth": depth, "nodes": [], "relations": []}

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        for start in matched:
            start_id = start["id"]
            nodes[start_id] = start

            # BFS via recursive CTE
            rows = self._db.execute("""
                WITH RECURSIVE traverse AS (
                    SELECT
                        e.id, e.type, e.label, e.metadata,
                        0 as hop,
                        CAST(e.id AS TEXT) as path
                    FROM entities e
                    WHERE e.id = ?

                    UNION ALL

                    SELECT
                        e2.id, e2.type, e2.label, e2.metadata,
                        t.hop + 1,
                        t.path || '>' || e2.id
                    FROM traverse t
                    JOIN relations r ON r.source_id = t.id
                    JOIN entities e2 ON e2.id = r.target_id
                    WHERE t.hop < ?
                      AND INSTR(t.path, e2.id) = 0  -- prevent cycles
                )
                SELECT DISTINCT id, type, label, metadata, hop
                FROM traverse
                ORDER BY hop, type
                LIMIT ?
            """, (start_id, depth, limit)).fetchall()

            for row in rows:
                nid = row["id"]
                if nid not in nodes:
                    try:
                        meta = json.loads(row["metadata"]) if row["metadata"] else {}
                    except json.JSONDecodeError:
                        meta = {}
                    nodes[nid] = {
                        "id": nid,
                        "type": row["type"],
                        "label": row["label"],
                        "metadata": meta,
                        "hop": row["hop"],
                    }

            # Get edges between discovered nodes
            node_ids = list(nodes.keys())
            if len(node_ids) > 1:
                placeholders = ",".join("?" * len(node_ids))
                edge_rows = self._db.execute(
                    f"""SELECT source_id, relation, target_id, confidence
                        FROM relations
                        WHERE source_id IN ({placeholders})
                        AND target_id IN ({placeholders})""",
                    node_ids + node_ids,
                ).fetchall()
                for er in edge_rows:
                    edges.append({
                        "source": er["source_id"],
                        "relation": er["relation"],
                        "target": er["target_id"],
                        "confidence": er["confidence"],
                    })

        return {
            "root": entity_label,
            "depth": depth,
            "nodes": list(nodes.values()),
            "relations": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def search_entities(self, query_str: str, limit: int = 10) -> list[dict]:
        """Search entities by label or metadata (FTS5 + LIKE fallback)."""
        results: list[dict] = []
        seen: set[str] = set()

        # FTS5 pass
        if self._has_fts:
            try:
                # Escape FTS5 special chars
                escaped = query_str.replace('"', '""')
                rows = self._db.execute(
                    """SELECT e.id, e.type, e.label, e.metadata, e.access_count
                       FROM entities_fts f JOIN entities e ON f.rowid = e.rowid
                       WHERE entities_fts MATCH ?
                       ORDER BY e.access_count DESC LIMIT ?""",
                    (f'"{escaped}"', limit),
                ).fetchall()
                for row in rows:
                    if row["id"] not in seen:
                        seen.add(row["id"])
                        results.append(self._row_to_entity(row))
            except Exception:
                pass

        # LIKE fallback
        if len(results) < limit:
            rows = self._db.execute(
                """SELECT id, type, label, metadata, access_count
                   FROM entities WHERE label LIKE ? OR metadata LIKE ?
                   ORDER BY access_count DESC LIMIT ?""",
                (f"%{query_str}%", f"%{query_str}%", limit),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen:
                    seen.add(row["id"])
                    results.append(self._row_to_entity(row))

        # Character-level for CJK
        if len(results) < limit:
            chars = [c for c in query_str if c.strip() and '一' <= c <= '鿿']
            for ch in chars[:3]:
                rows = self._db.execute(
                    """SELECT id, type, label, metadata, access_count
                       FROM entities WHERE label LIKE ?
                       ORDER BY access_count DESC LIMIT ?""",
                    (f"%{ch}%", limit),
                ).fetchall()
                for row in rows:
                    if row["id"] not in seen:
                        seen.add(row["id"])
                        results.append(self._row_to_entity(row))

        return results[:limit]

    def _row_to_entity(self, row) -> dict:
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, KeyError):
            meta = {}
        return {
            "id": row["id"],
            "type": row["type"],
            "label": row["label"],
            "metadata": meta,
            "access_count": row["access_count"] if "access_count" in row.keys() else 0,
        }

    # ── Auto-extraction ─────────────────────────────────────────────────────

    def auto_extract(self, conversation_text: str) -> int:
        """Extract entities and relations from conversation text using heuristics.

        Detects:
          - File paths (absolute and relative)
          - Error/exception names
          - Python module names
          - Mentioned technologies (frameworks, tools, databases)
          - Project names (capitalized words near "project"/"app")

        Returns the number of new entities added.
        """
        added = 0

        # File paths: /path/to/file.py, C:\path\to\file.py, ./src/main.py
        file_patterns = [
            r'(?:[a-zA-Z]:\\[\w\-.\\]+|/[\w\-./]+)\.(\w{1,10})',
            r'([\w\-]+\.(?:py|js|ts|rs|go|java|rb|php|css|html|json|yaml|toml|md))',
        ]
        for pat in file_patterns:
            for match in re.finditer(pat, conversation_text):
                fname = match.group(0)
                ext = fname.rsplit(".", 1)[-1]
                eid = f"file:{fname.replace('\\', '/')}"
                existing = self._db.execute(
                    "SELECT id FROM entities WHERE id = ?", (eid,)
                ).fetchone()
                if not existing:
                    self.add_entity(eid, "file", fname.rsplit("/")[-1].rsplit("\\")[-1],
                                   {"extension": ext, "full_path": fname})
                    added += 1

        # Error patterns
        error_patterns = [
            r'(?:Error|Exception|Traceback|panic|FAILED)[:\s]+(\w+(?:Error|Exception|Warning)?)',
            r'(?:raise|throw|throws)\s+(\w+(?:Error|Exception))',
            r'\b(\w+(?:Error|Exception))\b',  # Standalone: ValueError, KeyError, etc.
        ]
        for pat in error_patterns:
            for match in re.finditer(pat, conversation_text):
                err_name = match.group(1)
                eid = f"error:{err_name}"
                existing = self._db.execute(
                    "SELECT id FROM entities WHERE id = ?", (eid,)
                ).fetchone()
                if not existing:
                    self.add_entity(eid, "error", err_name, {"pattern": err_name})
                    added += 1

        # Technology mentions (common frameworks, tools, databases)
        tech_keywords = [
            "Docker", "Kubernetes", "React", "Vue", "Angular", "Flask",
            "FastAPI", "Django", "Spring", "PyTorch", "TensorFlow",
            "PostgreSQL", "MySQL", "MongoDB", "Redis", "RabbitMQ",
            "Git", "GitHub", "GitLab", "AWS", "Azure", "GCP",
            "TypeScript", "Rust", "Python", "JavaScript", "Go", "Java",
            "DeepSeek", "OpenAI", "Claude", "GPT", "LLM",
        ]
        for tech in tech_keywords:
            if tech.lower() in conversation_text.lower():
                eid = f"tech:{tech.lower()}"
                existing = self._db.execute(
                    "SELECT id FROM entities WHERE id = ?", (eid,)
                ).fetchone()
                if not existing:
                    self.add_entity(eid, "technology", tech, {"name": tech})
                    added += 1

        return added

    # ── Hybrid Search (FTS5 + Graph) ────────────────────────────────────────

    def search_hybrid(self, query_str: str, limit: int = 10, graph_depth: int = 1) -> dict:
        """Hybrid search combining FTS5 entity search + graph traversal.

        Args:
            query_str: Search query.
            limit: Max entities to return from initial search.
            graph_depth: How many hops to traverse from matched entities.

        Returns:
            {
                "direct_matches": [...entities...],
                "graph_results": [{entity, relations, neighbors}, ...],
                "total_nodes": N,
            }
        """
        direct = self.search_entities(query_str, limit=limit)

        graph_results = []
        all_nodes: dict[str, dict] = {}

        for entity in direct[:3]:  # Only expand top 3 to avoid bloat
            graph = self.query(entity["label"], depth=graph_depth, limit=20)
            graph_results.append({
                "entity": entity,
                "node_count": graph["node_count"],
                "nodes": graph["nodes"],
                "relations": graph["relations"],
            })
            for node in graph["nodes"]:
                if node["id"] not in all_nodes:
                    all_nodes[node["id"]] = node

        return {
            "direct_matches": direct,
            "graph_results": graph_results,
            "total_nodes": len(all_nodes),
        }

    # ── Statistics ──────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return knowledge graph statistics."""
        entities = self._db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relations = self._db.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        by_type = {}
        for row in self._db.execute(
            "SELECT type, COUNT(*) as cnt FROM entities GROUP BY type"
        ).fetchall():
            by_type[row["type"]] = row["cnt"]
        return {
            "entities": entities,
            "relations": relations,
            "by_type": by_type,
        }

    def close(self):
        """Close the database connection."""
        try:
            self._db.close()
        except Exception:
            pass
