"""Smoke test: hi_agent.runtime_adapter.temporal_health importable and instantiable."""

import pytest


@pytest.mark.smoke
def test_temporal_connection_state_importable():
    """TemporalConnectionState enum can be imported without error."""
    from hi_agent.runtime_adapter.temporal_health import TemporalConnectionState

    assert TemporalConnectionState is not None


@pytest.mark.smoke
def test_temporal_connection_health_report_importable():
    """TemporalConnectionHealthReport dataclass can be imported without error."""
    from hi_agent.runtime_adapter.temporal_health import TemporalConnectionHealthReport

    assert TemporalConnectionHealthReport is not None


@pytest.mark.smoke
def test_temporal_connection_health_check_importable():
    """TemporalConnectionHealthCheck can be imported without error."""
    from hi_agent.runtime_adapter.temporal_health import TemporalConnectionHealthCheck

    assert TemporalConnectionHealthCheck is not None


@pytest.mark.smoke
def test_temporal_connection_health_check_instantiable():
    """TemporalConnectionHealthCheck can be instantiated with a ping_fn."""
    from hi_agent.runtime_adapter.temporal_health import TemporalConnectionHealthCheck

    check = TemporalConnectionHealthCheck(ping_fn=lambda: 10.0)
    assert check is not None


@pytest.mark.smoke
def test_temporal_connection_health_check_healthy():
    """TemporalConnectionHealthCheck.check classifies a fast ping as healthy."""
    from hi_agent.runtime_adapter.temporal_health import (
        TemporalConnectionHealthCheck,
        TemporalConnectionState,
    )

    check = TemporalConnectionHealthCheck(
        ping_fn=lambda: 5.0,
        degraded_latency_ms=500.0,
    )
    report = check.check()
    assert report.state == TemporalConnectionState.HEALTHY
    assert report.healthy is True
    assert report.latency_ms == 5.0


@pytest.mark.smoke
def test_temporal_connection_health_check_unreachable():
    """TemporalConnectionHealthCheck.check classifies a failing ping as unreachable."""
    from hi_agent.runtime_adapter.temporal_health import (
        TemporalConnectionHealthCheck,
        TemporalConnectionState,
    )

    def _failing_ping() -> float:
        raise ConnectionError("timeout")

    check = TemporalConnectionHealthCheck(ping_fn=_failing_ping)
    report = check.check()
    assert report.state == TemporalConnectionState.UNREACHABLE
    assert report.healthy is False


@pytest.mark.smoke
def test_temporal_connection_state_values():
    """TemporalConnectionState enum has expected string values."""
    from hi_agent.runtime_adapter.temporal_health import TemporalConnectionState

    assert TemporalConnectionState.HEALTHY == "healthy"
    assert TemporalConnectionState.DEGRADED == "degraded"
    assert TemporalConnectionState.UNREACHABLE == "unreachable"
