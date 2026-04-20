"""Unit tests for observability metrics helpers."""

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
