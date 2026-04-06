"""In-memory flat knowledge store."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import time


@dataclass(frozen=True)
class KnowledgeRecord:
    """Stored knowledge item."""

    source: str
    key: str
    content: str
    tags: tuple[str, ...]
    vector: tuple[float, ...] | None
    updated_at: float


class InMemoryKnowledgeStore:
    """Flat knowledge store with deterministic retrieval ordering."""

    def __init__(self) -> None:
        """Initialize empty in-memory storage."""
        self._records: dict[tuple[str, str], KnowledgeRecord] = {}

    def upsert(
        self,
        *,
        source: str,
        key: str,
        content: str,
        tags: list[str] | tuple[str, ...] | None = None,
        vector: list[float] | tuple[float, ...] | None = None,
        now_value: float | None = None,
    ) -> KnowledgeRecord:
        """Insert or update record by composite identity (source, key)."""
        normalized_source = source.strip()
        normalized_key = key.strip()
        normalized_content = content.strip()
        if not normalized_source:
            raise ValueError("source must be a non-empty string")
        if not normalized_key:
            raise ValueError("key must be a non-empty string")
        if not normalized_content:
            raise ValueError("content must be a non-empty string")

        normalized_tags = tuple(sorted({tag.strip() for tag in (tags or []) if tag.strip()}))
        normalized_vector = tuple(float(value) for value in vector) if vector is not None else None
        updated_at = float(time() if now_value is None else now_value)
        record = KnowledgeRecord(
            source=normalized_source,
            key=normalized_key,
            content=normalized_content,
            tags=normalized_tags,
            vector=normalized_vector,
            updated_at=updated_at,
        )
        self._records[(normalized_source, normalized_key)] = record
        return record

    def all_records(self) -> list[KnowledgeRecord]:
        """Return all records in deterministic source/key order."""
        return [
            self._records[identity]
            for identity in sorted(self._records.keys(), key=lambda item: (item[0], item[1]))
        ]

    def get(self, *, source: str, key: str) -> KnowledgeRecord | None:
        """Get record by composite identity."""
        return self._records.get((source, key))

    def search(
        self,
        *,
        query: str,
        top_k: int = 5,
        tags: list[str] | tuple[str, ...] | None = None,
        query_vector: list[float] | tuple[float, ...] | None = None,
    ) -> list[tuple[KnowledgeRecord, float]]:
        """Flat search using token overlap and optional vector score.

        Scoring heuristic:
        - token overlap score has weight 1.0
        - vector dot-product has weight 0.1 (weak signal for MVP)
        """
        normalized_query = query.strip().lower()
        if not normalized_query:
            return []
        if top_k <= 0:
            return []

        query_tokens = {token for token in normalized_query.split() if token}
        required_tags = {tag.strip() for tag in (tags or []) if tag.strip()}
        query_vector_tuple = tuple(float(value) for value in query_vector) if query_vector else None

        scored: list[tuple[KnowledgeRecord, float]] = []
        for record in self._records.values():
            if required_tags and not required_tags.issubset(set(record.tags)):
                continue

            content_tokens = {token for token in record.content.lower().split() if token}
            overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
            vector_score = 0.0
            if (
                query_vector_tuple is not None
                and record.vector is not None
                and len(query_vector_tuple) == len(record.vector)
            ):
                vector_score = sum(
                    a * b
                    for a, b in zip(
                        query_vector_tuple,
                        record.vector,
                        strict=True,
                    )
                )
            final_score = overlap + (0.1 * vector_score)
            if final_score > 0:
                scored.append((record, final_score))

        scored.sort(
            key=lambda row: (
                -row[1],
                row[0].source,
                row[0].key,
            )
        )
        return scored[:top_k]

    def merge(
        self,
        *,
        source: str,
        key: str,
        extra_content: str,
        now_value: float | None = None,
    ) -> None:
        """Append extra content to an existing record for incremental ingest."""
        existing = self.get(source=source, key=key)
        if existing is None:
            raise ValueError(f"record ({source}, {key}) not found")
        merged_content = f"{existing.content}\n{extra_content.strip()}".strip()
        self._records[(source, key)] = replace(
            existing,
            content=merged_content,
            updated_at=float(time() if now_value is None else now_value),
        )
