"""Tests for temporal health command wrappers."""

from __future__ import annotations

from hi_agent.management.temporal_health_commands import (
    cmd_temporal_health_check,
    cmd_temporal_probe_check,
)


def test_cmd_temporal_health_check_healthy() -> None:
    """Low-latency ping should be classified as healthy."""
    payload = cmd_temporal_health_check(
        ping_fn=lambda: 12.5,
        degraded_latency_ms=100.0,
        now_fn=lambda: 10.0,
    )
    assert payload["command"] == "temporal_health_check"
    assert payload["state"] == "healthy"
    assert payload["healthy"] is True
    assert payload["latency_ms"] == 12.5


def test_cmd_temporal_health_check_unreachable_on_error() -> None:
    """Ping exception should produce unreachable state and error message."""

    def _ping_fail() -> float:
        raise RuntimeError("connection refused")

    payload = cmd_temporal_health_check(
        ping_fn=_ping_fail,
        degraded_latency_ms=100.0,
        now_fn=lambda: 10.0,
    )
    assert payload["healthy"] is False
    assert payload["state"] == "unreachable"
    assert "RuntimeError" in str(payload["error"])


def test_cmd_temporal_probe_check_connected_and_degraded() -> None:
    """Probe wrapper should expose degraded flag by latency threshold."""
    times = iter([100.0, 100.8]).__next__
    payload = cmd_temporal_probe_check(
        probe_fn=lambda: None,
        degraded_latency_ms=500.0,
        now_fn=times,
    )
    assert payload["command"] == "temporal_probe_check"
    assert payload["connected"] is True
    assert payload["degraded"] is True
    assert payload["latency_ms"] == 800.0
