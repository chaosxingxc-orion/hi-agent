"""Knowledge query helpers."""

from __future__ import annotations

from hi_agent.knowledge.store import InMemoryKnowledgeStore, KnowledgeRecord


def query_knowledge(
    *,
    store: InMemoryKnowledgeStore,
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    query_vector: list[float] | None = None,
) -> list[KnowledgeRecord]:
    """Retrieve top matching knowledge records."""
    rows = store.search(
        query=query,
        top_k=top_k,
        tags=tags,
        query_vector=query_vector,
    )
    return [record for record, _score in rows]
