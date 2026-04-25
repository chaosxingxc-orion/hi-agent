"""Smoke test: hi_agent.runtime_adapter.health importable and instantiable."""

import pytest


@pytest.mark.smoke
def test_adapter_health_monitor_importable():
    """AdapterHealthMonitor can be imported without error."""
    from hi_agent.runtime_adapter.health import AdapterHealthMonitor

    assert AdapterHealthMonitor is not None


@pytest.mark.smoke
def test_adapter_health_monitor_instantiable_defaults():
    """AdapterHealthMonitor can be instantiated with default args."""
    from hi_agent.runtime_adapter.health import AdapterHealthMonitor

    monitor = AdapterHealthMonitor()
    assert monitor is not None


@pytest.mark.smoke
def test_adapter_health_monitor_instantiable_custom():
    """AdapterHealthMonitor can be instantiated with explicit parameters."""
    from hi_agent.runtime_adapter.health import AdapterHealthMonitor

    monitor = AdapterHealthMonitor(
        window_seconds=60,
        degraded_error_rate=0.05,
        unhealthy_error_rate=0.3,
        degraded_latency_p95_ms=2000.0,
    )
    assert monitor is not None


@pytest.mark.smoke
def test_adapter_health_monitor_initial_status():
    """AdapterHealthMonitor.get_health returns a dict with expected keys when empty."""
    from hi_agent.runtime_adapter.health import AdapterHealthMonitor

    monitor = AdapterHealthMonitor()
    health = monitor.get_health()
    assert isinstance(health, dict)
    assert "status" in health
    assert "error_rate" in health
    # With zero calls, error_rate must be 0 (nothing has failed yet).
    assert health["error_rate"] == 0.0
