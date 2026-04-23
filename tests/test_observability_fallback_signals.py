"""Rule 14 signal-plumbing tests for DF-01.

Covers:
    * MetricsCollector.increment() logs ERROR for unknown metric names.
    * record_fallback() increments the fallback.<kind> counter.
    * record_fallback() emits a WARNING log carrying run_id, kind, reason.
    * record_fallback() appends to the per-run fallback_events registry.
"""

from __future__ import annotations

import logging

import pytest
from hi_agent.observability.collector import (
    MetricsCollector,
    set_metrics_collector,
)
from hi_agent.observability.fallback import (
    clear_fallback_events,
    get_fallback_events,
    record_fallback,
)


@pytest.fixture()
def collector() -> MetricsCollector:
    """Fresh MetricsCollector registered as the process singleton."""
    c = MetricsCollector()
    set_metrics_collector(c)
    try:
        yield c
    finally:
        set_metrics_collector(None)


def test_increment_unknown_metric_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown metric names must not be silently dropped — Rule 14."""
    c = MetricsCollector()
    with caplog.at_level(logging.ERROR, logger="hi_agent.observability.collector"):
        c.increment("nonexistent.metric", labels={"x": "y"})

    # At least one ERROR record mentions the offending name.
    matching = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and "nonexistent.metric" in r.getMessage()
    ]
    assert matching, f"expected ERROR log for unknown metric, got: {caplog.records!r}"
    # The log should surface the known-set so the operator can fix the wiring.
    assert any("known=" in r.getMessage() for r in matching)


def test_record_fallback_increments_counter(collector: MetricsCollector) -> None:
    """record_fallback increments fallback.<kind>."""
    before = collector.snapshot().get("fallback_llm", {})
    record_fallback(
        "llm",
        reason="retries_exhausted",
        run_id="run-a",
        extra={"model": "gpt-5.1"},
    )
    after = collector.snapshot().get("fallback_llm", {})

    before_total = sum(before.values()) if isinstance(before, dict) else 0
    after_total = sum(after.values()) if isinstance(after, dict) else 0
    assert after_total == before_total + 1

    # Cleanup run-scoped state.
    clear_fallback_events("run-a")


def test_record_fallback_emits_warning_log(
    collector: MetricsCollector,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """record_fallback emits a WARNING carrying run_id and kind."""
    with caplog.at_level(logging.WARNING, logger="hi_agent.observability.fallback"):
        record_fallback(
            "heuristic",
            reason="router_miss",
            run_id="run-b",
            extra={"component": "route_engine"},
        )

    matching = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "run-b" in r.getMessage()
        and "heuristic" in r.getMessage()
    ]
    assert matching, f"expected WARNING log with run_id+kind, got: {caplog.records!r}"

    clear_fallback_events("run-b")


def test_record_fallback_appends_to_run_events(collector: MetricsCollector) -> None:
    """record_fallback adds a well-shaped event to the per-run registry."""
    run_id = "run-c"
    clear_fallback_events(run_id)
    assert get_fallback_events(run_id) == []

    record_fallback(
        "capability",
        reason="heuristic_branch",
        run_id=run_id,
        extra={"capability": "research", "stage_id": "S1"},
    )

    events = get_fallback_events(run_id)
    assert len(events) == 1
    evt = events[0]
    assert evt["kind"] == "capability"
    assert evt["reason"] == "heuristic_branch"
    assert "ts" in evt and isinstance(evt["ts"], float)
    assert evt["extra"].get("capability") == "research"

    clear_fallback_events(run_id)
