"""Unit tests for ops governance decision helper."""

from __future__ import annotations

import pytest
from hi_agent.management.ops_governance import evaluate_ops_governance


def test_ops_governance_allows_deploy_when_all_green() -> None:
    """Healthy inputs should allow deployment without incident."""
    result = evaluate_ops_governance(
        readiness={"ready": True},
        signals={"overall_pressure": False},
        slo_snapshot={"success_target_met": True, "latency_target_met": True},
        alert_count=0,
    )
    assert result["allow_deploy"] is True
    assert result["require_incident"] is False
    assert result["escalation_level"] == "low"


def test_ops_governance_requires_incident_on_pressure() -> None:
    """Pressure or failing SLO should trigger incident requirement."""
    result = evaluate_ops_governance(
        readiness={"ready": True},
        signals={"overall_pressure": True},
        slo_snapshot={"success_target_met": False, "latency_target_met": True},
        alert_count=0,
    )
    assert result["allow_deploy"] is False
    assert result["require_incident"] is True
    assert result["escalation_level"] == "medium"


def test_ops_governance_alert_count_validation() -> None:
    """Negative alert count should be rejected."""
    with pytest.raises(ValueError):
        evaluate_ops_governance(
            readiness={"ready": True},
            signals={"overall_pressure": False},
            slo_snapshot={"success_target_met": True, "latency_target_met": True},
            alert_count=-1,
        )
