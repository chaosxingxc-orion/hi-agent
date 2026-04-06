"""Tests for operational alert helpers."""

from __future__ import annotations

from hi_agent.management.alerts import evaluate_operational_alerts


def test_evaluate_operational_alerts_returns_expected_alerts() -> None:
    """Risk flags should map to deterministic alert entries."""
    alerts = evaluate_operational_alerts(
        {
            "has_temporal_risk": True,
            "has_reconcile_pressure": True,
            "has_gate_pressure": False,
        }
    )
    assert [item["code"] for item in alerts] == ["temporal_risk", "reconcile_pressure"]


def test_evaluate_operational_alerts_returns_empty_when_no_risk() -> None:
    """No risk flags should produce no alerts."""
    assert (
        evaluate_operational_alerts(
            {
                "has_temporal_risk": False,
                "has_reconcile_pressure": False,
                "has_gate_pressure": False,
            }
        )
        == []
    )
