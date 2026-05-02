"""Knowledge entry dataclass for typed knowledge items."""

from __future__ import annotations

from dataclasses import dataclass, field


# W31 T-24' decision: value object — KG row carries tenant_id; tenant-agnostic.
# scope: process-internal
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
