"""Unit tests for observability metrics helpers and record_llm_request."""

from __future__ import annotations

import pytest
from hi_agent.observability.metrics import (
    RunMetricsRecord,
    aggregate_counters,
    avg_token_per_run,
    p95_latency,
    run_success_rate,
)


def test_run_success_rate_handles_empty_and_non_empty() -> None:
    """Success rate should return 0.0 for empty and ratio for non-empty input."""
    assert run_success_rate([]) == 0.0
    records = [
        RunMetricsRecord("run-1", "completed", 5, 5, 100),
        RunMetricsRecord("run-2", "failed", 4, 2, 200),
        RunMetricsRecord("run-3", "succeeded", 2, 8, 300),
    ]
    assert run_success_rate(records) == pytest.approx(2 / 3)


def test_avg_token_per_run_handles_empty_and_non_empty() -> None:
    """Average tokens should be computed over all runs."""
    assert avg_token_per_run([]) == 0.0
    records = [
        RunMetricsRecord("run-1", "completed", 10, 0, 100),
        RunMetricsRecord("run-2", "completed", 0, 20, 120),
    ]
    assert avg_token_per_run(records) == 15.0


def test_p95_latency_uses_nearest_rank() -> None:
    """p95 should use nearest-rank percentile."""
    records = [
        RunMetricsRecord(f"run-{index}", "completed", 1, 1, float(index)) for index in range(1, 21)
    ]
    # rank = ceil(0.95 * 20) = 19
    assert p95_latency(records) == 19.0
    assert p95_latency([]) == 0.0


def test_aggregate_counters_sums_per_key() -> None:
    """Counter aggregation should sum values key-by-key."""
    merged = aggregate_counters(
        [
            {"success": 2, "failed": 1},
            {"success": 3, "retried": 4},
            {"failed": 2},
        ]
    )
    assert merged == {"success": 5, "failed": 3, "retried": 4}


# ---------------------------------------------------------------------------
# record_llm_request tests
# ---------------------------------------------------------------------------


import contextlib

from hi_agent.observability.collector import MetricsCollector, set_metrics_collector
from hi_agent.observability.fallback import record_llm_request


@contextlib.contextmanager
def _isolated_collector():
    """Yield a fresh MetricsCollector registered as singleton; restore None on exit."""
    collector = MetricsCollector()
    set_metrics_collector(collector)
    try:
        yield collector
    finally:
        set_metrics_collector(None)


def test_record_llm_request_increments_counter() -> None:
    """record_llm_request must increment hi_agent_llm_requests_total exactly once."""
    with _isolated_collector() as c:
        record_llm_request(provider="openai", model="gpt-4", tier="s-tier")
        snap = c.snapshot()
        assert "hi_agent_llm_requests_total" in snap
        # The single increment should sum to 1.0 across all label buckets.
        total = sum(snap["hi_agent_llm_requests_total"].values())
        assert total == pytest.approx(1.0)


def test_record_llm_request_appears_in_prometheus_text() -> None:
    """/metrics text must contain hi_agent_llm_requests_total with correct labels."""
    with _isolated_collector() as c:
        record_llm_request(provider="openai", model="gpt-4", tier="s-tier")
        prom_text = c.to_prometheus_text()
        assert "hi_agent_llm_requests_total" in prom_text
        assert "openai" in prom_text
        assert "gpt-4" in prom_text
        assert "s-tier" in prom_text
        # Must be declared as a counter, not a gauge.
        assert "# TYPE hi_agent_llm_requests_total counter" in prom_text


def test_record_llm_request_counter_not_gauge() -> None:
    """hi_agent_llm_requests_total must be registered as a counter (monotonic)."""
    from hi_agent.observability.collector import _METRIC_DEFS

    defn = _METRIC_DEFS.get("hi_agent_llm_requests_total")
    assert defn is not None, "hi_agent_llm_requests_total missing from _METRIC_DEFS"
    assert defn.kind == "counter", f"expected counter, got {defn.kind!r}"


def test_record_llm_request_without_tier_label() -> None:
    """Tier label is optional; omitting it must not error and must still increment."""
    with _isolated_collector() as c:
        record_llm_request(provider="anthropic", model="claude-3-5-sonnet")
        snap = c.snapshot()
        total = sum(snap.get("hi_agent_llm_requests_total", {}).values())
        assert total == pytest.approx(1.0)


def test_record_llm_request_survives_no_collector() -> None:
    """When no collector is registered, record_llm_request must not raise."""
    set_metrics_collector(None)
    # Must complete without exception — telemetry cannot crash callers.
    record_llm_request(provider="openai", model="gpt-4o", tier="m-tier")
