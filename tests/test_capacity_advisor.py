"""Tests for server capacity tuning advisor."""

from __future__ import annotations

from hi_agent.management.capacity_advisor import (
    recommendations_to_payload,
    recommend_server_capacity_tuning,
)


def test_recommend_server_capacity_tuning_high_pressure() -> None:
    """Queue failures should trigger high-severity scale/throttle recommendation."""
    health = {
        "subsystems": {
            "run_manager": {
                "queue_utilization": 0.95,
                "queue_full_rejections": 5,
                "queue_timeouts": 2,
                "capacity": 4,
            }
        }
    }
    recs = recommend_server_capacity_tuning(health_payload=health, metrics_snapshot={})
    codes = {rec.code for rec in recs}
    assert "scale_or_throttle_immediately" in codes


def test_recommend_server_capacity_tuning_overprovisioned() -> None:
    """Very low queue utilization should emit cost-saving recommendation."""
    health = {
        "subsystems": {
            "run_manager": {
                "queue_utilization": 0.02,
                "queue_full_rejections": 0,
                "queue_timeouts": 0,
                "capacity": 8,
            }
        }
    }
    recs = recommend_server_capacity_tuning(health_payload=health, metrics_snapshot={})
    codes = {rec.code for rec in recs}
    assert "capacity_overprovisioned" in codes


def test_recommendations_to_payload_shape() -> None:
    """Payload conversion should return JSON-friendly rows."""
    health = {
        "subsystems": {
            "run_manager": {
                "queue_utilization": 0.9,
                "queue_full_rejections": 1,
                "queue_timeouts": 0,
                "capacity": 2,
            }
        }
    }
    rows = recommendations_to_payload(
        recommend_server_capacity_tuning(health_payload=health, metrics_snapshot={})
    )
    assert isinstance(rows, list)
    assert rows
    assert {"code", "severity", "summary", "action"}.issubset(rows[0].keys())

