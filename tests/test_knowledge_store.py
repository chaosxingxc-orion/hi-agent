"""Unit tests for flat knowledge store and ingest/query helpers."""

from __future__ import annotations

from hi_agent.knowledge.ingest import IngestPolicy, ingest_run_summary
from hi_agent.knowledge.query import query_knowledge
from hi_agent.knowledge.store import InMemoryKnowledgeStore


def test_store_upsert_and_dedup_by_source_key() -> None:
    """Upsert should keep one record per (source, key)."""
    store = InMemoryKnowledgeStore()
    first = store.upsert(source="run", key="r-1", content="alpha beta", tags=["x"])
    second = store.upsert(source="run", key="r-1", content="alpha gamma", tags=["y"])

    assert first.key == second.key
    assert len(store.all_records()) == 1
    assert store.get(source="run", key="r-1").content == "alpha gamma"


def test_search_uses_overlap_and_vector_signal() -> None:
    """Search should prioritize lexical overlap and use vector as weak tie-break."""
    store = InMemoryKnowledgeStore()
    store.upsert(source="run", key="r-1", content="database indexing strategy", vector=[1.0, 0.0])
    store.upsert(source="run", key="r-2", content="database migration rollback", vector=[0.5, 0.5])

    rows = store.search(query="database strategy", top_k=2, query_vector=[1.0, 0.0])
    assert [row[0].key for row in rows] == ["r-1", "r-2"]


def test_ingest_policy_controls_write() -> None:
    """Ingest policy should skip or write based on run status and labels."""
    store = InMemoryKnowledgeStore()

    skipped = ingest_run_summary(
        store=store,
        run_id="r-3",
        source="run",
        summary="will not persist",
        policy=IngestPolicy.ON_SUCCESS,
        run_status="failed",
    )
    assert skipped is None

    written = ingest_run_summary(
        store=store,
        run_id="r-4",
        source="run",
        summary="persisted summary",
        policy=IngestPolicy.ON_LABELED,
        run_status="failed",
        labeled=True,
    )
    assert written is not None
    assert query_knowledge(store=store, query="persisted", top_k=1)[0].key == "r-4"

