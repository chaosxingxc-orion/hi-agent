"""Integration tests for reconcile runtime operational controller."""

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


def test_reconcile_runtime_manual_flow_reduces_backlog_and_recovers_readiness(tmp_path) -> None:
    """Manual reconcile should clear backlog and recover operational readiness."""
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
        interval_seconds=60.0,
        clock=lambda: 1.0,
    )
    controller = ReconcileRuntimeController(
        supervisor,
        dependencies={"runtime": True, "kernel": True},
        reconcile_backlog_threshold=2,
    )

    readiness_before = controller.readiness(recent_error_count=0)
    manual_report = controller.run_manual(max_rounds=1)
    readiness_after = controller.readiness(recent_error_count=0)
    status_after = controller.status()

    assert readiness_before.ready is True
    assert manual_report.reconcile_report is not None
    assert manual_report.reconcile_report.applied == 1
    assert readiness_after.ready is True
    assert status_after.backlog_size == 0
    assert healthy_backend.calls == [stage_id]
