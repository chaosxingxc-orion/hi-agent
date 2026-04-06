"""Filtering helpers for knowledge query results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _read_field(item: object, field: str, default: Any = None) -> Any:
    """Read field value from either mapping-like or attribute-like item."""
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def filter_knowledge_results(
    results: Iterable[object],
    *,
    min_score: float | None = None,
    required_tags: set[str] | frozenset[str] | list[str] | tuple[str, ...] | None = None,
    source: str | None = None,
) -> list[object]:
    """Filter knowledge results while preserving original ordering.

    Args:
      results: Iterable of results (dict or object with score/tags/source fields).
      min_score: Optional minimum score threshold.
      required_tags: Optional tag set that each result must contain.
      source: Optional exact source value required.

    Returns:
      Filtered results in original stable order.
    """
    normalized_required_tags = set(required_tags or [])

    filtered: list[object] = []
    for item in results:
        if min_score is not None:
            score = _read_field(item, "score")
            if not isinstance(score, int | float) or float(score) < float(min_score):
                continue

        if normalized_required_tags:
            tags_value = _read_field(item, "tags", ())
            if isinstance(tags_value, str):
                tags_set = {tags_value}
            elif isinstance(tags_value, Iterable):
                tags_set = set(tags_value)
            else:
                tags_set = set()
            if not normalized_required_tags.issubset(tags_set):
                continue

        if source is not None:
            item_source = _read_field(item, "source")
            if item_source != source:
                continue

        filtered.append(item)

    return filtered
