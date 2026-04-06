"""Integration tests for daemon/runtime-controller reconcile flow."""

from __future__ import annotations

import pytest
from hi_agent.management import ReconcileRuntimeController, ReconcileSupervisor
from hi_agent.runtime_adapter import (
    FileBackedConsistencyJournal,
    KernelAdapter,
    ReconcileLoop,
    RuntimeAdapterBackendError,
)


class _FailingBackend:
    """Backend stub that always fails open_stage writes."""

    def open_stage(self, stage_id: str) -> None:
        raise RuntimeError(f"planned open_stage failure: {stage_id}")


class _HealthyBackend:
    """Backend stub that records successful open_stage calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(stage_id)


@pytest.mark.parametrize(
    ("path", "expected_trigger"),
    [("tick", "tick"), ("manual", "manual")],
)
def test_reconcile_daemon_runtime_controller_flow(
    tmp_path, path: str, expected_trigger: str
) -> None:
    """Issue should be journaled, then reconciled via daemon tick or manual path."""
    stage_id = "S1_understand"
    journal = FileBackedConsistencyJournal(tmp_path / "consistency.journal")

    failing_adapter = KernelAdapter(
        strict_mode=True,
        backend=_FailingBackend(),
        consistency_journal=journal,
    )
    with pytest.raises(RuntimeAdapterBackendError):
        failing_adapter.open_stage(stage_id)

    healthy_backend = _HealthyBackend()
    loop = ReconcileLoop(backend=healthy_backend, journal=journal)
    supervisor = ReconcileSupervisor(
        reconcile_loop=loop,
        journal=journal,
        interval_seconds=1.0,
        periodic_max_rounds=1,
        clock=lambda: 1.0,
    )
    controller = ReconcileRuntimeController(
        supervisor,
        dependencies={"runtime": True, "kernel": True},
        reconcile_backlog_threshold=1,
    )

    status_before = controller.status()
    readiness_before = controller.readiness(recent_error_count=0)
    assert status_before.backlog_size == 1
    assert status_before.last_trigger is None
    assert status_before.last_executed is None
    assert readiness_before.ready is False
    assert readiness_before.reconcile_backlog == 1

    report = controller.tick() if path == "tick" else controller.run_manual(max_rounds=1)

    status_after = controller.status()
    readiness_after = controller.readiness(recent_error_count=0)

    assert report.executed is True
    assert report.trigger == expected_trigger
    assert report.reconcile_report is not None
    assert report.reconcile_report.applied == 1
    assert report.reconcile_report.failed == 0
    assert report.backlog_size == 0

    assert status_after.backlog_size == 0
    assert status_after.recent_reconcile_failures == 0
    assert status_after.dead_letter_count == 0
    assert status_after.last_trigger == expected_trigger
    assert status_after.last_executed is True

    assert readiness_after.ready is True
    assert readiness_after.reconcile_backlog == 0
    assert readiness_after.recent_reconcile_failures == 0
    assert healthy_backend.calls == [stage_id]
