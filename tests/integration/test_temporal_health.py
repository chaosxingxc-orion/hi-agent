"""Unit tests for temporal connectivity health checks."""

from __future__ import annotations

from hi_agent.runtime_adapter.temporal_health import check_temporal_connection


def test_check_temporal_connection_reports_connected_fast_probe() -> None:
    """Probe should be connected and healthy when latency is below threshold."""
    times = iter([100.0, 100.05]).__next__
    health = check_temporal_connection(lambda: None, now_fn=times, degraded_latency_ms=100.0)
    assert health.connected is True
    assert health.degraded is False
    assert health.latency_ms == 50.0


def test_check_temporal_connection_reports_degraded_when_latency_high() -> None:
    """Probe should be marked degraded if latency is above threshold."""
    times = iter([100.0, 100.8]).__next__
    health = check_temporal_connection(lambda: None, now_fn=times, degraded_latency_ms=500.0)
    assert health.connected is True
    assert health.degraded is True
    assert health.latency_ms == 800.0


def test_check_temporal_connection_reports_disconnected_on_exception() -> None:
    """Probe exceptions should produce disconnected health with reason."""
    times = iter([100.0, 100.2]).__next__

    def _probe() -> None:
        raise RuntimeError("temporal unavailable")

    health = check_temporal_connection(_probe, now_fn=times, degraded_latency_ms=500.0)
    assert health.connected is False
    assert health.degraded is True
    assert health.reason == "temporal unavailable"
