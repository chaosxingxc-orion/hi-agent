"""Unit tests for knowledge result filtering."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.knowledge.filters import filter_knowledge_results


@dataclass(frozen=True)
class _ResultObj:
    key: str
    score: float
    tags: tuple[str, ...]
    source: str


def test_filter_preserves_stable_order() -> None:
    """Filtering should keep original ordering for matched results."""
    items: list[object] = [
        {"key": "a", "score": 0.9, "tags": ["prod"], "source": "wiki"},
        {"key": "b", "score": 0.3, "tags": ["prod"], "source": "wiki"},
        {"key": "c", "score": 0.7, "tags": ["ops"], "source": "doc"},
    ]

    filtered = filter_knowledge_results(items, min_score=0.5)
    assert [item["key"] for item in filtered if isinstance(item, dict)] == ["a", "c"]


def test_filter_supports_object_results() -> None:
    """Attribute-style objects should be filtered correctly."""
    items = [
        _ResultObj(key="a", score=0.91, tags=("prod", "urgent"), source="wiki"),
        _ResultObj(key="b", score=0.70, tags=("prod",), source="doc"),
        _ResultObj(key="c", score=0.45, tags=("ops",), source="wiki"),
    ]

    filtered = filter_knowledge_results(
        items,
        min_score=0.7,
        required_tags={"prod"},
        source="wiki",
    )
    assert [item.key for item in filtered] == ["a"]


def test_filter_required_tags_and_source_on_dict_results() -> None:
    """Tag/source filters should work for dict-based results."""
    items: list[object] = [
        {"key": "a", "score": 0.8, "tags": ["prod", "urgent"], "source": "wiki"},
        {"key": "b", "score": 0.9, "tags": ["prod"], "source": "doc"},
        {"key": "c", "score": 0.95, "tags": ["urgent"], "source": "wiki"},
    ]

    filtered = filter_knowledge_results(
        items,
        required_tags={"prod", "urgent"},
        source="wiki",
    )
    assert [item["key"] for item in filtered if isinstance(item, dict)] == ["a"]


def test_filter_combined_with_missing_fields_is_deterministic() -> None:
    """Missing fields should be treated as non-matching without raising errors."""
    items: list[object] = [
        {"key": "a", "score": 0.9, "tags": ["prod"], "source": "wiki"},
        {"key": "b"},
        _ResultObj(key="c", score=0.75, tags=("prod",), source="wiki"),
    ]

    filtered = filter_knowledge_results(items, min_score=0.8, required_tags={"prod"}, source="wiki")
    # Only first item matches all filters.
    assert len(filtered) == 1
    assert isinstance(filtered[0], dict)
    assert filtered[0]["key"] == "a"
