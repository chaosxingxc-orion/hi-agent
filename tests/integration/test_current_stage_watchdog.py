"""W32-C.9 integration test for the current_stage watchdog.

Per Rule 8 step-5, ``current_stage`` must be non-None within 30s on every
turn. The watchdog scans non-terminal runs every 30s and emits a Rule-7
alarm + WARNING log when ``current_stage`` is None for >60s on a run that
has not reached a terminal state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from hi_agent.observability import silent_degradation
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


def _stuck_run(run_id: str, age_seconds: float):
    """Build a fake ManagedRun-shaped object with current_stage=None."""
    created_at = (
        datetime.now(UTC) - timedelta(seconds=age_seconds)
    ).isoformat()
    run = MagicMock()
    run.run_id = run_id
    run.state = "running"
    run.current_stage = None
    run.created_at = created_at
    return run


def test_watchdog_fires_alarm_for_run_stuck_with_current_stage_none():
    """Inject a run aged >60s with current_stage=None; assert the watchdog
    fires the Rule-7 fallback_events entry within ~35s."""
    server = AgentServer(rate_limit_rps=10000)

    # A list_runs that returns one stuck run; the watchdog scans this.
    server.run_manager.list_runs = MagicMock(  # type: ignore[method-assign]  expiry_wave: permanent
        return_value=[_stuck_run("stuck-run-1", age_seconds=120.0)]
    )

    # Snapshot the current fallback_events count for current_stage_watchdog.
    initial_events = [
        e for e in silent_degradation.get_fallback_events()
        if e.get("component") == "current_stage_watchdog"
    ]
    initial_count = len(initial_events)

    # Drive lifespan via TestClient. The watchdog runs every 30s — wait up
    # to 35s for it to fire once.
    with TestClient(server.app, raise_server_exceptions=False) as client:
        client.get("/health")
        import time
        deadline = time.monotonic() + 35.0
        observed = initial_count
        while time.monotonic() < deadline:
            current = [
                e for e in silent_degradation.get_fallback_events()
                if e.get("component") == "current_stage_watchdog"
                and e.get("reason") == "current_stage_none_over_60s"
                and e.get("run_id") == "stuck-run-1"
            ]
            if len(current) > 0:
                observed = len(current)
                break
            time.sleep(0.5)

    assert observed > 0, (
        "current_stage_watchdog did not record a Rule-7 fallback "
        "event for the stuck run within 35s"
    )

    # Inspect the alarm record.
    alarm_events = [
        e for e in silent_degradation.get_fallback_events()
        if e.get("component") == "current_stage_watchdog"
        and e.get("run_id") == "stuck-run-1"
    ]
    assert alarm_events
    last = alarm_events[-1]
    assert last["reason"] == "current_stage_none_over_60s"
    assert last.get("age_seconds", 0) >= 60.0


def test_watchdog_does_not_fire_for_terminal_runs():
    """A run in terminal state must not trigger the watchdog."""
    server = AgentServer(rate_limit_rps=10000)

    terminal_run = MagicMock()
    terminal_run.run_id = "terminal-run-1"
    terminal_run.state = "completed"
    terminal_run.current_stage = None
    terminal_run.created_at = (
        datetime.now(UTC) - timedelta(seconds=120)
    ).isoformat()

    server.run_manager.list_runs = MagicMock(  # type: ignore[method-assign]  expiry_wave: permanent
        return_value=[terminal_run]
    )

    with TestClient(server.app, raise_server_exceptions=False) as client:
        client.get("/health")
        import time
        time.sleep(33.0)  # one full watchdog cycle (interval=30s + grace)
        events = [
            e for e in silent_degradation.get_fallback_events()
            if e.get("component") == "current_stage_watchdog"
            and e.get("run_id") == "terminal-run-1"
        ]

    assert events == [], (
        "watchdog should NOT fire for terminal runs, but found: " + str(events)
    )
