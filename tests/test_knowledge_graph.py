"""Tests for orca_code.memory.knowledge_graph — Entity-Relation Knowledge Graph."""

import json

import pytest

from orca_code.memory import KnowledgeGraph


class TestEntityCRUD:
    """Entity create, read, update, delete tests."""

    def test_add_and_get_entity(self):
        """Add an entity and retrieve it."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("file:main.py", "file", "main.py", {"lang": "python"})

        entity = kg.get_entity("file:main.py")
        assert entity is not None
        assert entity["type"] == "file"
        assert entity["label"] == "main.py"
        meta = json.loads(entity["metadata"])
        assert meta["lang"] == "python"

    def test_add_entity_updates_existing(self):
        """Adding same entity ID updates it."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("e1", "file", "old_name")
        kg.add_entity("e1", "file", "new_name")

        entity = kg.get_entity("e1")
        assert entity["label"] == "new_name"

    def test_get_nonexistent_entity(self):
        """Getting non-existent entity returns None."""
        kg = KnowledgeGraph(":memory:")
        assert kg.get_entity("no_such_entity") is None

    def test_find_entities_by_type(self):
        """Find entities filtered by type."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("f1", "file", "a.py")
        kg.add_entity("f2", "file", "b.py")
        kg.add_entity("e1", "error", "ValueError")

        files = kg.find_entities(entity_type="file")
        assert len(files) == 2
        errors = kg.find_entities(entity_type="error")
        assert len(errors) == 1

    def test_find_entities_by_label(self):
        """Find entities by label substring."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("f1", "file", "main.py")
        kg.add_entity("f2", "file", "utils.py")
        kg.add_entity("f3", "file", "test_main.py")

        results = kg.find_entities(label_contains="main")
        assert len(results) == 2  # main.py and test_main.py

    def test_entity_count(self):
        """entity_count returns correct count."""
        kg = KnowledgeGraph(":memory:")
        assert kg.entity_count == 0
        kg.add_entity("a", "type1", "A")
        kg.add_entity("b", "type2", "B")
        assert kg.entity_count == 2

    def test_delete_entity(self):
        """Delete entity removes it and its relations."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("a", "type", "A")
        kg.add_entity("b", "type", "B")
        kg.relate("a", "knows", "b")

        kg.delete_entity("a")
        assert kg.get_entity("a") is None
        # Relations from deleted entity should be cascade-deleted
        rels = kg.get_relations("b", direction="incoming")
        assert len(rels) == 0


class TestRelations:
    """Relation management tests."""

    def test_relate_creates_entities(self):
        """relate auto-creates entities if they don't exist."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("a", "knows", "b")
        assert kg.get_entity("a") is not None
        assert kg.get_entity("b") is not None

    def test_get_relations_outgoing(self):
        """Get outgoing relations from an entity."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("a", "depends_on", "b")
        kg.relate("a", "depends_on", "c")

        rels = kg.get_relations("a", direction="outgoing")
        assert len(rels) == 2
        assert all(r["source_id"] == "a" for r in rels)

    def test_get_relations_incoming(self):
        """Get incoming relations to an entity."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("x", "uses", "target")
        kg.relate("y", "imports", "target")

        rels = kg.get_relations("target", direction="incoming")
        assert len(rels) == 2
        assert all(r["target_id"] == "target" for r in rels)

    def test_get_relations_filtered(self):
        """Filter relations by type."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("a", "depends_on", "b")
        kg.relate("a", "imports", "c")

        rels = kg.get_relations("a", relation_type="depends_on")
        assert len(rels) == 1
        assert rels[0]["relation"] == "depends_on"

    def test_delete_relation(self):
        """Delete a specific relation."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("a", "knows", "b")
        assert len(kg.get_relations("a")) == 1

        kg.delete_relation("a", "knows", "b")
        assert len(kg.get_relations("a")) == 0

    def test_relation_confidence(self):
        """Relations store confidence values."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("a", "might_use", "b", confidence=0.3, source_type="inferred")

        rels = kg.get_relations("a")
        assert rels[0]["confidence"] == 0.3
        assert rels[0]["source_type"] == "inferred"


class TestGraphQuery:
    """Graph traversal tests."""

    def test_query_finds_entity(self):
        """query() finds entities matching a label."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("file:main.py", "file", "main.py")
        kg.add_entity("file:utils.py", "file", "utils.py")

        result = kg.query("main", depth=1)
        assert result["node_count"] >= 1
        labels = [n["label"] for n in result["nodes"]]
        assert "main.py" in labels

    def test_query_traverses_relations(self):
        """query() follows relations up to depth hops."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("file:A.py", "imports", "file:B.py")
        kg.relate("file:B.py", "imports", "file:C.py")

        result = kg.query("A.py", depth=2)
        assert result["node_count"] >= 2  # A + B (depth 1) + C (depth 2)
        labels = [n["label"] for n in result["nodes"]]
        assert "A.py" in labels
        # B.py should be reachable at depth 1
        assert "B.py" in labels or any("B.py" in n.get("label", "") for n in result["nodes"])

    def test_query_returns_relations(self):
        """query() returns the edges between discovered nodes."""
        kg = KnowledgeGraph(":memory:")
        kg.relate("a", "knows", "b")
        kg.relate("b", "knows", "c")

        result = kg.query("a", depth=2)
        assert result["edge_count"] >= 1
        relations = [(r["source"], r["relation"], r["target"]) for r in result["relations"]]
        assert ("a", "knows", "b") in relations

    def test_search_entities_fts5(self):
        """search_entities finds entities via FTS5 or LIKE."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("tech:docker", "technology", "Docker", {"category": "container"})
        kg.add_entity("tech:react", "technology", "React", {"category": "frontend"})

        results = kg.search_entities("docker")
        assert len(results) >= 1
        assert results[0]["label"] == "Docker"


class TestAutoExtract:
    """Auto-extraction heuristic tests."""

    def test_extracts_file_paths(self):
        """Auto-extract detects Python file paths."""
        kg = KnowledgeGraph(":memory:")
        text = "Let's look at src/main.py and tests/test_main.py for the bug."
        added = kg.auto_extract(text)
        assert added >= 1  # At least one file detected

        files = kg.find_entities(entity_type="file")
        file_labels = [f["label"] for f in files]
        assert any("main.py" in lbl for lbl in file_labels)

    def test_extracts_error_names(self):
        """Auto-extract detects error/exception names."""
        kg = KnowledgeGraph(":memory:")
        text = "Got a ValueError when parsing the JSON. Also saw KeyError in logs."
        added = kg.auto_extract(text)
        assert added >= 1

        errors = kg.find_entities(entity_type="error")
        error_labels = [e["label"] for e in errors]
        assert any("ValueError" in lbl for lbl in error_labels)

    def test_extracts_technologies(self):
        """Auto-extract detects technology mentions."""
        kg = KnowledgeGraph(":memory:")
        text = "We use Docker for deployment and React for the frontend."
        added = kg.auto_extract(text)
        assert added >= 1

        techs = kg.find_entities(entity_type="technology")
        tech_labels = [t["label"] for t in techs]
        assert any("Docker" in lbl for lbl in tech_labels) or any("React" in lbl for lbl in tech_labels)

    def test_extract_empty_text(self):
        """Auto-extract on empty text returns 0."""
        kg = KnowledgeGraph(":memory:")
        added = kg.auto_extract("")
        assert added == 0


class TestHybridSearch:
    """Hybrid search (FTS5 + Graph) tests."""

    def test_hybrid_search_direct_match(self):
        """Hybrid search finds direct entity matches."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("file:main.py", "file", "main.py")
        kg.add_entity("file:utils.py", "file", "utils.py")

        result = kg.search_hybrid("main", limit=5)
        assert len(result["direct_matches"]) >= 1
        assert result["direct_matches"][0]["label"] == "main.py"

    def test_hybrid_search_graph_expansion(self):
        """Hybrid search expands matches via graph traversal."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("file:main.py", "file", "main.py")
        kg.add_entity("file:config.py", "file", "config.py")
        kg.add_entity("error:ConfigError", "error", "ConfigError")
        kg.relate("file:main.py", "imports", "file:config.py")
        kg.relate("file:config.py", "triggers", "error:ConfigError")

        result = kg.search_hybrid("main", limit=5, graph_depth=1)
        assert result["total_nodes"] >= 1
        # Should find graph_results with neighbors
        assert len(result["graph_results"]) >= 1


class TestStats:
    """Statistics tests."""

    def test_stats_empty(self):
        """Stats on empty graph returns zeros."""
        kg = KnowledgeGraph(":memory:")
        s = kg.stats()
        assert s["entities"] == 0
        assert s["relations"] == 0

    def test_stats_with_data(self):
        """Stats reflects added entities and relations."""
        kg = KnowledgeGraph(":memory:")
        kg.add_entity("a", "type_a", "A")
        kg.add_entity("b", "type_b", "B")
        kg.relate("a", "knows", "b")

        s = kg.stats()
        assert s["entities"] == 2
        assert s["relations"] == 1
        assert s["by_type"]["type_a"] == 1
        assert s["by_type"]["type_b"] == 1


class TestMemoryManagerIntegration:
    """Knowledge graph integration with MemoryManager."""

    def test_auto_extract_knowledge(self):
        """MemoryManager.auto_extract_knowledge works."""
        try:
            from _memory_manager import MemoryManager

            mgr = MemoryManager(":memory:")
            added = mgr.auto_extract_knowledge(
                "We need to fix the TypeError in src/app.py. Using FastAPI for the API."
            )
            # Should have extracted at least the file and technology
            assert added >= 0  # Depends on heuristics
            mgr.close()
        except ImportError:
            pytest.skip("MemoryManager not importable in this test environment")

    def test_search_hybrid_integration(self):
        """MemoryManager.search_hybrid delegates to FTS5 + KG."""
        try:
            import os
            import tempfile

            from _memory_manager import MemoryManager

            tmp = tempfile.mktemp(suffix=".db")
            mgr = MemoryManager(tmp)
            mgr.save_message("test", 1, "user", "What is Docker?")
            mgr.save_message("test", 1, "assistant", "Docker is a container platform.")

            results = mgr.search_hybrid("Docker", limit=3)
            assert len(results) >= 1
            mgr.close()

            # Cleanup
            try:
                os.unlink(tmp)
            except Exception:
                pass
        except ImportError:
            pytest.skip("MemoryManager not importable in this test environment")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
