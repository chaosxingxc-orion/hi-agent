"""Tests for route audit timeline helper."""

from __future__ import annotations

import pytest
from hi_agent.route_engine.audit_timeline import build_audit_timeline


def test_build_audit_timeline_sorts_by_ts_with_stable_order() -> None:
    """Rows should be sorted by ts ascending, preserving insertion on ties."""
    audits = [
        {
            "ts": 20.0,
            "stage_id": "S2",
            "selected_branch": "b2",
            "confidence": 0.8,
            "band": "ok",
        },
        {
            "ts": 10.0,
            "stage_id": "S1",
            "selected_branch": "b1",
            "confidence": 0.4,
            "band": "low",
        },
        {
            "ts": 20.0,
            "stage_id": "S2b",
            "selected_branch": "b2x",
            "confidence": 0.7,
            "band": "borderline",
        },
    ]

    rows = build_audit_timeline(audits)

    assert [row["stage"] for row in rows] == ["S1", "S2", "S2b"]
    assert [row["branch"] for row in rows] == ["b1", "b2", "b2x"]


def test_build_audit_timeline_pushes_missing_ts_to_end() -> None:
    """Rows with missing timestamp should be placed after timed rows."""
    audits = [
        {
            "stage_id": "S_missing",
            "selected_branch": "b0",
            "confidence": 0.2,
            "band": "low",
        },
        {
            "ts": 5.0,
            "stage_id": "S_timed",
            "selected_branch": "b1",
            "confidence": 0.9,
            "band": "ok",
        },
        {
            "stage_id": "S_missing_2",
            "selected_branch": "b2",
            "confidence": 0.6,
            "band": "borderline",
        },
    ]

    rows = build_audit_timeline(audits)
    assert [row["stage"] for row in rows] == ["S_timed", "S_missing", "S_missing_2"]
    assert rows[1]["ts"] is None
    assert rows[2]["ts"] is None


def test_build_audit_timeline_can_hide_confidence_fields() -> None:
    """Confidence/band should be None when include_confidence is disabled."""
    audits = [
        {
            "ts": 1.0,
            "stage_id": "S1",
            "selected_branch": "b1",
            "confidence": 0.9,
            "band": "ok",
        },
    ]
    rows = build_audit_timeline(audits, include_confidence=False)
    assert rows[0]["confidence"] is None
    assert rows[0]["band"] is None


def test_build_audit_timeline_rejects_non_numeric_ts() -> None:
    """Non-numeric timestamp values should fail fast."""
    with pytest.raises(ValueError, match="ts must be numeric when provided"):
        build_audit_timeline([{"ts": "not-a-number", "stage_id": "S1", "selected_branch": "b1"}])
