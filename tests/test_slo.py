"""Tests for SLO snapshot helper."""

from __future__ import annotations

import pytest
from hi_agent.management.slo import build_slo_snapshot


def test_build_slo_snapshot_evaluates_targets() -> None:
    """Snapshot should contain target pass/fail booleans."""
    snapshot = build_slo_snapshot(
        run_success_rate=0.995,
        latency_p95_ms=3000.0,
        success_target=0.99,
        latency_target_ms=5000.0,
    )
    assert snapshot.success_target_met is True
    assert snapshot.latency_target_met is True


def test_build_slo_snapshot_rejects_invalid_values() -> None:
    """Invalid values should raise ValueError."""
    with pytest.raises(ValueError):
        build_slo_snapshot(run_success_rate=1.2, latency_p95_ms=100.0)
    with pytest.raises(ValueError):
        build_slo_snapshot(run_success_rate=0.9, latency_p95_ms=-1.0)
