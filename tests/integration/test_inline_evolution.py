"""Integration checks for inline knowledge ingest/query behavior."""

from __future__ import annotations

from hi_agent.knowledge.ingest import IngestPolicy, ingest_run_summary
from hi_agent.knowledge.query import query_knowledge
from hi_agent.knowledge.store import InMemoryKnowledgeStore


def test_inline_ingest_then_query_roundtrip() -> None:
    """A completed run summary should become queryable knowledge."""
    store = InMemoryKnowledgeStore()
    ingest_run_summary(
        store=store,
        run_id="run-inline-1",
        source="run_summary",
        summary="Use rollback guard rails when deploying schema changes",
        policy=IngestPolicy.ON_SUCCESS,
        run_status="completed",
        tags=["ops", "db"],
    )

    hits = query_knowledge(store=store, query="schema rollback", top_k=3)
    assert [record.key for record in hits] == ["run-inline-1"]
