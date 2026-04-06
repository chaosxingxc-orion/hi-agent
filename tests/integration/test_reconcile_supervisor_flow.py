"""Integration test for manual-trigger reconcile supervisor flow."""

from __future__ import annotations

import pytest
from hi_agent.management import ReconcileSupervisor
from hi_agent.runtime_adapter import (
    FileBackedConsistencyJournal,
    KernelAdapter,
    ReconcileLoop,
    RuntimeAdapterBackendError,
)


class _FailingBackend:
    def open_stage(self, stage_id: str) -> None:
        raise RuntimeError(f"planned open_stage failure: {stage_id}")


class _HealthyBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def open_stage(self, stage_id: str) -> None:
        self.calls.append(stage_id)


def test_manual_trigger_reconcile_supervisor_flow(tmp_path) -> None:
    """Manual reconcile should apply journaled issues and reduce supervisor backlog."""
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
        interval_seconds=30.0,
        clock=lambda: 1.0,
    )

    backlog_before = supervisor.backlog_size()
    report = supervisor.run_manual(max_rounds=1)
    backlog_after = supervisor.backlog_size()

    assert backlog_before == 1
    assert backlog_after < backlog_before
    assert report.reconcile_report is not None
    assert report.reconcile_report.applied > 0
    assert healthy_backend.calls == [stage_id]
