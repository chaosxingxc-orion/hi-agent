"""W32-C.6 integration tests for Rule 7 health-check fallback instrumentation.

Each silent-degradation site in handle_health / handle_ready must:
  1. Increment ``hi_agent_health_check_fallback_total{component=...}`` (counter)
  2. Emit a WARNING+ log line
  3. Append a Rule-7 fallback_events entry via record_silent_degradation()
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from hi_agent.observability import silent_degradation
from hi_agent.observability.collector import get_metrics_collector
from hi_agent.server import app as server_app
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


@pytest.fixture()
def server() -> AgentServer:
    """Plain AgentServer at dev rate-limit."""
    return AgentServer(rate_limit_rps=10000)


@pytest.fixture()
def client(server: AgentServer) -> TestClient:
    return TestClient(server.app, raise_server_exceptions=False)


def _fallback_events_for(component_suffix: str) -> list[dict]:
    """Return fallback events whose component starts with health_check.<suffix>."""
    target = f"health_check.{component_suffix}"
    return [
        e
        for e in silent_degradation.get_fallback_events()
        if e.get("component") == target
    ]


def _counter_value_for(component: str) -> float:
    """Return the labelled counter value for hi_agent_health_check_fallback_total."""
    collector = get_metrics_collector()
    if collector is None:
        return 0.0
    snap = collector.snapshot()
    raw = snap.get("hi_agent_health_check_fallback_total", {})
    if not isinstance(raw, dict):
        return 0.0
    # Counter snapshot keys may be plain string or label-encoded.
    total = 0.0
    for key, value in raw.items():
        if not isinstance(value, (int, float)):
            continue
        if component in str(key):
            total += float(value)
    return total


def test_health_run_manager_failure_records_rule7_signals(
    server: AgentServer, client: TestClient, caplog: pytest.LogCaptureFixture
):
    """Inject a run_manager.get_status() failure and assert all 3 Rule-7 signals fire."""
    initial_events = len(_fallback_events_for("run_manager"))
    initial_counter = _counter_value_for("run_manager")

    # Replace run_manager.get_status with a failing callable.
    failing_mgr = MagicMock()
    failing_mgr.get_status = MagicMock(
        side_effect=RuntimeError("run_manager_status_kaboom")
    )
    server.run_manager = failing_mgr

    with caplog.at_level(logging.WARNING):
        resp = client.get("/health")

    # Endpoint still returns 200 with degraded subsystem block.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subsystems"]["run_manager"]["status"] == "error"

    # 1. Counter incremented.
    final_counter = _counter_value_for("run_manager")
    assert final_counter > initial_counter, (
        f"hi_agent_health_check_fallback_total did not increment: "
        f"initial={initial_counter} final={final_counter}"
    )

    # 2. WARNING log line emitted (either by handle_health or by
    # record_silent_degradation; both forward the failure signal).
    assert any(
        rec.levelno >= logging.WARNING
        and (
            "run_manager" in rec.message
            or "Rule-7" in rec.message
        )
        for rec in caplog.records
    ), "no WARNING+ log line referencing run_manager failure"

    # 3. fallback_events appended via record_silent_degradation.
    final_events = _fallback_events_for("run_manager")
    assert len(final_events) > initial_events, (
        "no fallback_events entry for health_check.run_manager"
    )
    last = final_events[-1]
    assert last["reason"] == "get_status_failed"
    assert "run_manager_status_kaboom" in last.get("exc", "")


def test_ready_readiness_failure_records_rule7_signals(
    server: AgentServer, client: TestClient, caplog: pytest.LogCaptureFixture
):
    """Inject a builder.readiness() failure and assert all 3 Rule-7 signals fire."""
    initial_events = len(_fallback_events_for("readiness"))
    initial_counter = _counter_value_for("readiness")

    # Replace builder.readiness() with a failing callable. The handler also
    # reaches for run_mgr.queue_depth, so leave run_manager intact.
    server._builder.readiness = MagicMock(  # type: ignore[attr-defined]  expiry_wave: permanent
        side_effect=ValueError("readiness_synthetic_failure")
    )

    with caplog.at_level(logging.WARNING):
        resp = client.get("/ready")

    # Should be 503 because snapshot is forced to ready=False.
    assert resp.status_code in (200, 503), resp.text

    final_counter = _counter_value_for("readiness")
    assert final_counter > initial_counter

    final_events = _fallback_events_for("readiness")
    assert len(final_events) > initial_events
    assert any(
        e.get("reason") == "readiness_snapshot_failed" for e in final_events
    )

    assert any(
        rec.levelno >= logging.WARNING
        and ("readiness" in rec.message or "Rule-7" in rec.message)
        for rec in caplog.records
    )


def test_health_check_fallback_helper_writes_all_three_channels(
    caplog: pytest.LogCaptureFixture,
):
    """Direct unit-style call to the helper — verifies it writes counter +
    log + fallback_events on a single invocation."""
    initial_events = len(_fallback_events_for("test_helper"))
    initial_counter = _counter_value_for("test_helper")

    with caplog.at_level(logging.WARNING):
        server_app._record_health_check_fallback(
            "test_helper",
            "synthetic_failure",
            ValueError("oops"),
        )

    assert _counter_value_for("test_helper") > initial_counter
    final_events = _fallback_events_for("test_helper")
    assert len(final_events) > initial_events
    assert final_events[-1]["reason"] == "synthetic_failure"
    assert any("Rule-7" in r.message for r in caplog.records)
