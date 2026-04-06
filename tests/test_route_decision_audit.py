"""Tests for route decision audit helpers."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.decision_audit import (
    is_low_confidence,
    persist_route_decision_audit,
    record_route_decision_audit,
)


def test_record_route_decision_audit_returns_normalized_payload() -> None:
    """Audit helper should normalize and return all required fields."""
    payload = record_route_decision_audit(
        run_id=" run-1 ",
        stage_id=" S2_gather ",
        engine=" hybrid ",
        provenance=" llm_fallback ",
        confidence=0.62,
        selected_branch=" b-2 ",
        candidates=[{"branch_id": "b-1"}, {"branch_id": "b-2"}],
        now_fn=lambda: 123.0,
    )
    assert payload == {
        "run_id": "run-1",
        "stage_id": "S2_gather",
        "engine": "hybrid",
        "provenance": "llm_fallback",
        "confidence": 0.62,
        "selected_branch": "b-2",
        "candidates": [{"branch_id": "b-1"}, {"branch_id": "b-2"}],
        "ts": 123.0,
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_record_route_decision_audit_rejects_invalid_confidence(confidence: float) -> None:
    """Confidence must be in the closed interval [0, 1]."""
    with pytest.raises(ValueError, match="confidence must be in range"):
        record_route_decision_audit(
            run_id="run-1",
            stage_id="S2",
            engine="rule",
            provenance="rule",
            confidence=confidence,
            selected_branch="b-1",
        )


def test_is_low_confidence_works_with_default_threshold() -> None:
    """Low-confidence helper should compare against default threshold."""
    assert is_low_confidence({"confidence": 0.5}) is True
    assert is_low_confidence({"confidence": 0.8}) is False
    assert is_low_confidence({"confidence": None}) is False


def test_is_low_confidence_threshold_edges_are_stable() -> None:
    """Exact-threshold values should not be treated as low confidence."""
    assert is_low_confidence({"confidence": 0.7}, threshold=0.7) is False
    assert is_low_confidence({"confidence": 0.0}, threshold=0.0) is False
    assert is_low_confidence({"confidence": 0.99}, threshold=1.0) is True


def test_is_low_confidence_rejects_invalid_threshold_or_confidence() -> None:
    """Helper should validate threshold and confidence boundaries."""
    with pytest.raises(ValueError, match="threshold must be in range"):
        is_low_confidence({"confidence": 0.5}, threshold=1.2)
    with pytest.raises(ValueError, match="audit confidence must be in range"):
        is_low_confidence({"confidence": -0.3}, threshold=0.7)


def test_persist_route_decision_audit_appends_and_returns_payload() -> None:
    """Persist helper should append generated payload and return it."""

    class _FakeStore:
        def __init__(self) -> None:
            self.items: list[dict[str, object]] = []

        def append(self, audit: dict[str, object]) -> None:
            self.items.append(dict(audit))

    store = _FakeStore()
    payload = persist_route_decision_audit(
        store,
        run_id="run-9",
        stage_id="S3_build",
        engine="hybrid",
        provenance="llm_fallback",
        selected_branch="b-5",
        confidence=0.55,
        candidates=[{"branch_id": "b-5"}],
        now_fn=lambda: 999.0,
    )
    assert payload["run_id"] == "run-9"
    assert payload["ts"] == 999.0
    assert len(store.items) == 1
    assert store.items[0] == payload


def test_persist_route_decision_audit_requires_append_method() -> None:
    """Store argument must implement callable append(audit)."""
    with pytest.raises(TypeError, match="append"):
        persist_route_decision_audit(
            object(),
            run_id="run-1",
            stage_id="S1_understand",
            engine="rule",
            provenance="rule_engine",
            selected_branch="b-1",
        )
