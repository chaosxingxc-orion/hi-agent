"""Tests for incident runbook generator."""

from __future__ import annotations

import pytest
from hi_agent.management.runbook import build_incident_runbook


def test_build_incident_runbook_high_priority_and_limit() -> None:
    """High severity should prioritize stabilization steps and respect max_steps."""
    report = {
        "service": "trace-core",
        "severity": "high",
        "key_facts": ["alerts=3"],
        "recommendations": [
            "Check runtime substrate connectivity and failover readiness.",
            "Drain reconcile backlog and inspect recent reconcile failures.",
        ],
    }
    runbook = build_incident_runbook(report, max_steps=4)
    assert runbook["title"] == "trace-core incident runbook"
    assert runbook["severity"] == "high"
    assert runbook["owner_hint"] == "incident-commander"
    assert len(runbook["steps"]) == 4
    assert runbook["steps"][0].startswith("Stabilize production impact")


def test_build_incident_runbook_low_priority() -> None:
    """Low severity should keep lightweight owner hint and baseline step."""
    report = {
        "service": "trace-core",
        "severity": "low",
        "recommendations": ["No immediate action required; continue routine monitoring."],
    }
    runbook = build_incident_runbook(report)
    assert runbook["severity"] == "low"
    assert runbook["owner_hint"] == "service-owner"
    assert runbook["steps"][0].startswith("Validate monitoring data")


@pytest.mark.parametrize(
    ("report", "max_steps"),
    [
        ({}, 3),
        ({"severity": "unknown"}, 3),
        ({"severity": "medium", "recommendations": "bad"}, 3),
        ({"severity": "medium", "recommendations": []}, 0),
    ],
)
def test_build_incident_runbook_validation_errors(report: dict, max_steps: int) -> None:
    """Invalid input should raise ValueError with deterministic checks."""
    with pytest.raises(ValueError):
        build_incident_runbook(report, max_steps=max_steps)
