"""Tests for SLO command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.management.slo_commands import cmd_slo_burn_rate, cmd_slo_evaluate


def test_cmd_slo_evaluate_returns_pass_fail_payload() -> None:
    """Evaluate command should return normalized pass/fail payload."""
    payload = cmd_slo_evaluate(
        {"run_success_rate": 0.995, "latency_p95_ms": 1200.0},
        objective={"success_target": 0.99, "latency_target_ms": 2000.0},
    )
    assert payload["command"] == "slo_evaluate"
    assert payload["success_target_met"] is True
    assert payload["latency_target_met"] is True
    assert payload["passed"] is True


def test_cmd_slo_evaluate_flags_failure_when_targets_not_met() -> None:
    """Evaluate command should fail if any objective target is missed."""
    payload = cmd_slo_evaluate(
        {"run_success_rate": 0.95, "latency_p95_ms": 7000.0},
        objective={"success_target": 0.99, "latency_target_ms": 5000.0},
    )
    assert payload["success_target_met"] is False
    assert payload["latency_target_met"] is False
    assert payload["passed"] is False


def test_cmd_slo_burn_rate_computes_and_validates_inputs() -> None:
    """Burn-rate command should compute values and reject invalid inputs."""
    payload = cmd_slo_burn_rate(0.8, 4)
    assert payload == {
        "command": "slo_burn_rate",
        "error_budget_remaining": 0.8,
        "window_hours": 4.0,
        "burn_rate_per_hour": pytest.approx(0.05),
    }

    with pytest.raises(ValueError, match="error_budget_remaining must be in \\[0, 1\\]"):
        cmd_slo_burn_rate(1.1, 4)
    with pytest.raises(ValueError, match="window_hours must be > 0"):
        cmd_slo_burn_rate(0.8, 0)
