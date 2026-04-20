"""Security / integrity tests for the JSON-based RetrievalEngine index cache.

Ensures that:
- The cache round-trips correctly.
- Tampered, stale-fingerprint, and wrong-schema caches trigger a rebuild.
- No pickle usage remains in retrieval_engine.py.
"""
from __future__ import annotations

import json
import pathlib

from hi_agent.knowledge.retrieval_engine import RetrievalEngine
from hi_agent.knowledge.wiki import KnowledgeWiki, WikiPage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wiki() -> KnowledgeWiki:
    wiki = KnowledgeWiki()
    wiki.add_page(
        WikiPage(
            page_id="page-a",
            title="Alpha Page",
            content="Alpha content about retrieval and caching.",
            tags=["alpha"],
        )
    )
    wiki.add_page(
        WikiPage(
            page_id="page-b",
            title="Beta Page",
            content="Beta content about indexing and search.",
            tags=["beta"],
        )
    )
    return wiki


def _build_engine(tmp_path: pathlib.Path) -> RetrievalEngine:
    """Build an engine, populate and persist the index, return it."""
    storage = str(tmp_path / "knowledge")
    engine = RetrievalEngine(wiki=_make_wiki(), storage_dir=storage)
    engine.build_index()
    return engine


def _cache_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "knowledge" / ".index_cache.json"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJsonCacheLoadsCorrectly:
    def test_json_cache_loads_correctly(self, tmp_path):
        """Build an index, save it, create a fresh engine that loads from JSON,
        and verify retrieve() returns results.
        """
        storage = str(tmp_path / "knowledge")
        engine = RetrievalEngine(wiki=_make_wiki(), storage_dir=storage)
        engine.build_index()

        cache_file = _cache_path(tmp_path)
        assert cache_file.exists(), "JSON cache file must exist after build_index()"

        # Load a second engine from the same storage_dir.
        engine2 = RetrievalEngine(wiki=_make_wiki(), storage_dir=storage)
        loaded = engine2._load_index()
        assert loaded is True, "_load_index() must return True for a valid cache"
        assert engine2._tfidf.doc_count == engine._tfidf.doc_count

        engine2._indexed = True
        result = engine2.retrieve("alpha retrieval", budget_tokens=5000)
        assert len(result.items) >= 1

    def test_json_cache_schema_version_present(self, tmp_path):
        _ = _build_engine(tmp_path)
        data = json.loads(_cache_path(tmp_path).read_text(encoding="utf-8"))
        assert data["schema_version"] == RetrievalEngine._CACHE_SCHEMA_VERSION
        assert "fingerprint" in data
        assert "built_at" in data
        assert "docs" in data
        assert "doc_tokens" in data
        assert "idf" in data


class TestTamperedCacheTriggersRebuild:
    def test_tampered_cache_triggers_rebuild(self, tmp_path):
        """Corrupt the JSON on disk; _load_index() must return False."""
        _build_engine(tmp_path)
        cache_file = _cache_path(tmp_path)
        cache_file.write_text("{ this is not valid json !!!}", encoding="utf-8")

        engine2 = RetrievalEngine(storage_dir=str(tmp_path / "knowledge"))
        result = engine2._load_index()
        assert result is False, "Corrupted JSON must return False"


class TestWrongFingerprintTriggersRebuild:
    def test_wrong_fingerprint_triggers_rebuild(self, tmp_path):
        """Mutate fingerprint in the JSON; _load_index() must return False."""
        _build_engine(tmp_path)
        cache_file = _cache_path(tmp_path)
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["fingerprint"] = "0" * 64  # wrong hash
        cache_file.write_text(json.dumps(data), encoding="utf-8")

        engine2 = RetrievalEngine(storage_dir=str(tmp_path / "knowledge"))
        result = engine2._load_index()
        assert result is False, "Fingerprint mismatch must return False"


class TestWrongSchemaVersionTriggersRebuild:
    def test_wrong_schema_version_triggers_rebuild(self, tmp_path):
        """Set schema_version=99; _load_index() must return False."""
        _build_engine(tmp_path)
        cache_file = _cache_path(tmp_path)
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["schema_version"] = 99
        cache_file.write_text(json.dumps(data), encoding="utf-8")

        engine2 = RetrievalEngine(storage_dir=str(tmp_path / "knowledge"))
        result = engine2._load_index()
        assert result is False, "Wrong schema_version must return False"


class TestNoPickleInModule:
    def test_no_pickle_in_module(self):
        """retrieval_engine.py must contain no pickle references."""
        source = pathlib.Path(
            "hi_agent/knowledge/retrieval_engine.py"
        ).read_text(encoding="utf-8")
        assert "pickle" not in source, (
            "Found 'pickle' in hi_agent/knowledge/retrieval_engine.py — "
            "remove all pickle usage"
        )
