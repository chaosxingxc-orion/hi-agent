"""Integration flow for route decision audit + store."""

from __future__ import annotations

from hi_agent.route_engine.decision_audit import record_route_decision_audit
from hi_agent.route_engine.decision_audit_store import InMemoryDecisionAuditStore


def test_route_decision_audit_can_round_trip_through_store() -> None:
    """Recorded audit payload should round-trip through in-memory store."""
    audit = record_route_decision_audit(
        run_id="run-1",
        stage_id="S2_gather",
        engine="hybrid",
        provenance="llm_fallback",
        confidence=0.42,
        selected_branch="branch-a",
        candidates=[{"branch_id": "branch-a"}, {"branch_id": "branch-b"}],
        now_fn=lambda: 10.0,
    )
    store = InMemoryDecisionAuditStore()
    store.append(audit)

    latest = store.latest_by_stage("run-1", "S2_gather")
    assert latest is not None
    assert latest["selected_branch"] == "branch-a"
    assert latest["confidence"] == 0.42
