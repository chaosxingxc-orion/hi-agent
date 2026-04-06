"""L0 raw memory records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# Simple negation indicators used for contradiction heuristic.
_NEGATION_PAIRS: list[tuple[str, str]] = [
    ("success", "failure"),
    ("succeeded", "failed"),
    ("completed", "incomplete"),
    ("approved", "rejected"),
    ("valid", "invalid"),
    ("confirmed", "denied"),
    ("resolved", "unresolved"),
    ("true", "false"),
]


@dataclass
class RawEventRecord:
    """Uncompressed event payload captured from runtime."""

    event_type: str
    payload: dict
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tags: list[str] = field(default_factory=list)


def _payload_text(record: RawEventRecord) -> str:
    """Flatten payload values into a lowercase string for matching."""
    return " ".join(str(v) for v in record.payload.values()).lower()


def _check_contradiction(
    new_record: RawEventRecord,
    existing: list[RawEventRecord],
) -> list[str]:
    """Return contradiction tags if *new_record* negates any existing record."""
    new_text = _payload_text(new_record)
    tags: list[str] = []
    for idx, old in enumerate(existing):
        old_text = _payload_text(old)
        for pos, neg in _NEGATION_PAIRS:
            if (pos in new_text and neg in old_text) or (
                neg in new_text and pos in old_text
            ):
                tags.append(f"contradiction:{idx}")
                break
    return tags


class RawMemoryStore:
    """In-memory L0 event store."""

    def __init__(self) -> None:
        """Initialize empty raw-memory record list."""
        self.records: list[RawEventRecord] = []

    def append(
        self,
        record: RawEventRecord,
        *,
        stage_id: str | None = None,
    ) -> None:
        """Append one record, auto-tagging contradictions within the same stage."""
        if stage_id is not None:
            same_stage = [
                r
                for r in self.records
                if r.payload.get("stage_id") == stage_id
            ]
            contradiction_tags = _check_contradiction(record, same_stage)
            record.tags.extend(contradiction_tags)
        self.records.append(record)

    def list_all(self) -> list[RawEventRecord]:
        """Return all records in insertion order."""
        return list(self.records)
