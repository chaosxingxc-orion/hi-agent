"""Knowledge entry dataclass for typed knowledge items."""

from __future__ import annotations

from dataclasses import dataclass, field


# scope: process-internal — value object only. Tenant scoping lives on the SqliteKnowledgeGraphBackend row, not the dataclass. Every read/write path (KnowledgeManager.ingest_text / query / get_stats / lint) MUST pass tenant_id explicitly. The ingest pipeline rejects an absent tenant_id under research/prod posture per check_contract_spine_completeness.py.  # noqa: E501  # single-line annotation required by check_contract_spine_completeness.py
@dataclass
class KnowledgeEntry:
    """A typed knowledge item for the knowledge store.

    Attributes:
        entry_id: Unique identifier for this entry.
        content: The knowledge content text.
        entry_type: Category of knowledge (fact, method, rule, procedure).
        tags: Free-form classification tags.
        source: Origin of this knowledge (e.g. run ID, document).
        confidence: Confidence score between 0.0 and 1.0.
        created_at: ISO-8601 timestamp of creation.
    """

    entry_id: str
    content: str
    entry_type: str = "fact"  # fact, method, rule, procedure
    tags: list[str] = field(default_factory=list)
    source: str = ""
    confidence: float = 1.0
    created_at: str = ""
