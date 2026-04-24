"""DF-10: capability heuristic branch must record a fallback signal.

The generic LLM-backed capability handler produced by
:func:`hi_agent.capability.defaults.make_llm_capability_handler` falls back
to a heuristic response when no LLM gateway is available *and* heuristic
fallback is permitted.  That path previously left no operator-visible
trace; Rule 14 requires a fallback counter + log + per-run event.
"""

from __future__ import annotations

import pytest
from hi_agent.capability.defaults import make_llm_capability_handler
from hi_agent.observability.collector import MetricsCollector, set_metrics_collector
from hi_agent.observability.fallback import (
    clear_fallback_events,
    get_fallback_events,
)


@pytest.fixture()
def heuristic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the handler into the heuristic branch."""
    monkeypatch.setenv("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
    # Make sure HI_AGENT_ENV doesn't mask the flag.
    monkeypatch.delenv("HI_AGENT_ENV", raising=False)


@pytest.fixture()
def collector() -> MetricsCollector:
    c = MetricsCollector()
    set_metrics_collector(c)
    try:
        yield c
    finally:
        set_metrics_collector(None)


def test_capability_heuristic_branch_records_fallback(
    heuristic_env: None,
    collector: MetricsCollector,
) -> None:
    """A heuristic capability response must be accompanied by a record_fallback call."""
    handler = make_llm_capability_handler(
        "test_cap",
        "You are a test capability.",
        gateway=None,  # forces the heuristic branch
    )

    run_id = "run-heuristic-1"
    clear_fallback_events(run_id)

    result = handler(
        {
            "goal": "demo goal",
            "stage_id": "S1",
            "run_id": run_id,
        }
    )

    # The handler returns a heuristic success.
    assert result.get("_heuristic") is True

    # Rule 14: a fallback event for kind="capability" was appended.
    events = get_fallback_events(run_id)
    assert len(events) >= 1, f"expected >=1 fallback event, got {events!r}"
    assert any(e["kind"] == "capability" for e in events)

    # The capability counter was incremented.
    snap = collector.snapshot().get("fallback_capability", {})
    total = sum(snap.values()) if isinstance(snap, dict) else 0
    assert total >= 1

    clear_fallback_events(run_id)
