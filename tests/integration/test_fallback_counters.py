"""Integration test: per-kind Prometheus counters wired in record_fallback() (TE-4).

Verifies that calling record_fallback() for each of the four canonical kinds
increments the corresponding hi_agent_<kind>_fallback_total counter in the
MetricsCollector singleton.

No MagicMock on the metrics collector.
"""
from __future__ import annotations

import pytest
from hi_agent.observability.collector import MetricsCollector, set_metrics_collector
from hi_agent.observability.fallback import clear_fallback_events, record_fallback


@pytest.fixture(autouse=True)
def isolated_collector():
    """Register a fresh MetricsCollector and tear it down after each test."""
    collector = MetricsCollector()
    set_metrics_collector(collector)
    yield collector
    set_metrics_collector(None)


def _total(snapshot: dict, metric_name: str) -> float:
    """Sum all label buckets for a given metric name in a snapshot."""
    bucket = snapshot.get(metric_name, {})
    if isinstance(bucket, dict):
        return sum(bucket.values())
    return 0.0


def test_llm_fallback_counter_incremented(isolated_collector):
    """record_fallback('llm', ...) increments hi_agent_llm_fallback_total."""
    clear_fallback_events("run-te4-llm")
    record_fallback("llm", reason="retries_exhausted", run_id="run-te4-llm")
    snapshot = isolated_collector.snapshot()
    assert _total(snapshot, "hi_agent_llm_fallback_total") >= 1, (
        f"hi_agent_llm_fallback_total not incremented; snapshot={snapshot}"
    )


def test_heuristic_fallback_counter_incremented(isolated_collector):
    """record_fallback('heuristic', ...) increments hi_agent_heuristic_fallback_total."""
    clear_fallback_events("run-te4-heuristic")
    record_fallback("heuristic", reason="model_unavailable", run_id="run-te4-heuristic")
    snapshot = isolated_collector.snapshot()
    assert _total(snapshot, "hi_agent_heuristic_fallback_total") >= 1, (
        f"hi_agent_heuristic_fallback_total not incremented; snapshot={snapshot}"
    )


def test_capability_fallback_counter_incremented(isolated_collector):
    """record_fallback('capability', ...) increments hi_agent_capability_fallback_total."""
    clear_fallback_events("run-te4-cap")
    record_fallback("capability", reason="handler_degraded", run_id="run-te4-cap")
    snapshot = isolated_collector.snapshot()
    assert _total(snapshot, "hi_agent_capability_fallback_total") >= 1, (
        f"hi_agent_capability_fallback_total not incremented; snapshot={snapshot}"
    )


def test_route_fallback_counter_incremented(isolated_collector):
    """record_fallback('route', ...) increments hi_agent_route_fallback_total."""
    clear_fallback_events("run-te4-route")
    record_fallback("route", reason="rule_miss", run_id="run-te4-route")
    snapshot = isolated_collector.snapshot()
    assert _total(snapshot, "hi_agent_route_fallback_total") >= 1, (
        f"hi_agent_route_fallback_total not incremented; snapshot={snapshot}"
    )


def test_named_counters_visible_in_prometheus_text(isolated_collector):
    """All four hi_agent_*_fallback_total counters appear in Prometheus text output."""
    clear_fallback_events("run-te4-prom")
    for kind in ("llm", "heuristic", "capability", "route"):
        record_fallback(kind, reason="test", run_id="run-te4-prom")
    text = isolated_collector.to_prometheus_text()
    for kind in ("llm", "heuristic", "capability", "route"):
        expected = f"hi_agent_{kind}_fallback_total"
        assert expected in text, (
            f"'{expected}' not found in Prometheus output:\n{text[:2000]}"
        )
