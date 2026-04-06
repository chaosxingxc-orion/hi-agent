"""Knowledge ingest helpers for run outcomes."""

from __future__ import annotations

from enum import StrEnum

from hi_agent.knowledge.store import InMemoryKnowledgeStore, KnowledgeRecord


class IngestPolicy(StrEnum):
    """Ingest policy modes."""

    ON_SUCCESS = "on_success"
    ON_LABELED = "on_labeled"
    NEVER = "never"


def should_ingest(
    *,
    policy: IngestPolicy,
    run_status: str,
    labeled: bool = False,
) -> bool:
    """Return whether current run data should be ingested."""
    if policy is IngestPolicy.NEVER:
        return False
    if policy is IngestPolicy.ON_LABELED:
        return labeled
    return run_status.strip().lower() in {"completed", "succeeded"}


def ingest_run_summary(
    *,
    store: InMemoryKnowledgeStore,
    run_id: str,
    source: str,
    summary: str,
    policy: IngestPolicy,
    run_status: str,
    labeled: bool = False,
    tags: list[str] | None = None,
    vector: list[float] | None = None,
) -> KnowledgeRecord | None:
    """Ingest run summary into store according to policy."""
    if not should_ingest(policy=policy, run_status=run_status, labeled=labeled):
        return None
    return store.upsert(
        source=source,
        key=run_id,
        content=summary,
        tags=tags,
        vector=vector,
    )

