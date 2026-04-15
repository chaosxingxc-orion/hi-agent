"""L0 raw memory records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

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
    """In-memory L0 event store with optional JSONL file persistence."""

    def __init__(
        self,
        run_id: str = "",
        base_dir: str | Path = "",
    ) -> None:
        """Initialize raw-memory record list.

        Args:
            run_id: Run identifier. When non-empty (with base_dir), enables
                file persistence to {base_dir}/logs/memory/L0/{run_id}.jsonl.
            base_dir: Base directory for JSONL output. Ignored when run_id is empty.
        """
        self.records: list[RawEventRecord] = []
        self._run_id = run_id
        self._file: IO[str] | None = None
        self._base_dir: Path | None = None

        if run_id and base_dir:
            self._base_dir = Path(base_dir)
            log_path = self._base_dir / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = log_path.open("a", encoding="utf-8")

    def close(self) -> None:
        """Flush and close the JSONL file handle. Safe to call multiple times."""
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None

    def __enter__(self) -> RawMemoryStore:
        """Enter context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit context manager — closes the file handle."""
        self.close()

    def append(
        self,
        record: RawEventRecord,
        *,
        stage_id: str | None = None,
    ) -> None:
        """Append one record, auto-tagging contradictions within the same stage."""
        if self._run_id and self._file is None:
            raise ValueError("RawMemoryStore is closed")
        if stage_id is not None:
            same_stage = [
                r
                for r in self.records
                if r.payload.get("stage_id") == stage_id
            ]
            contradiction_tags = _check_contradiction(record, same_stage)
            record.tags.extend(contradiction_tags)
        self.records.append(record)

        if self._file is not None:
            line = json.dumps(
                {
                    "timestamp": record.timestamp,
                    "run_id": self._run_id,
                    "content": record.payload,
                    "metadata": {"event_type": record.event_type, "tags": record.tags},
                },
                ensure_ascii=False,
            )
            self._file.write(line + "\n")

    def flush(self) -> None:
        """Flush the JSONL file handle to disk. No-op when file persistence is off."""
        if self._file is not None:
            self._file.flush()

    def list_all(self) -> list[RawEventRecord]:
        """Return all records in insertion order."""
        return list(self.records)
