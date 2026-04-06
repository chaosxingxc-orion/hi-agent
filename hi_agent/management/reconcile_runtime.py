"""Operational runtime controller for consistency reconcile management."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.management.health import (
    OperationalReadinessReport,
    build_operational_readiness_report,
)
from hi_agent.management.reconcile_supervisor import (
    ReconcileSupervisor,
    ReconcileSupervisorReport,
)


@dataclass(frozen=True)
class ReconcileRuntimeStatus:
    """Snapshot of reconcile runtime operational state."""

    backlog_size: int
    recent_reconcile_failures: int
    dead_letter_count: int
    last_trigger: str | None
    last_executed: bool | None


class ReconcileRuntimeController:
    """High-level operational entrypoint for reconcile supervision."""

    def __init__(
        self,
        supervisor: ReconcileSupervisor,
        *,
        dependencies: dict[str, bool] | None = None,
        reconcile_backlog_threshold: int = 1,
    ) -> None:
        """Initialize controller.

        Args:
          supervisor: Reconcile supervisor instance.
          dependencies: Optional dependency status map.
          reconcile_backlog_threshold: Backlog threshold for readiness.
        """
        if reconcile_backlog_threshold < 0:
            raise ValueError("reconcile_backlog_threshold must be >= 0")
        self._supervisor = supervisor
        self._dependencies = dict(dependencies or {"runtime": True})
        self._reconcile_backlog_threshold = reconcile_backlog_threshold

    def tick(self) -> ReconcileSupervisorReport:
        """Run one periodic tick and return supervisor report."""
        return self._supervisor.tick()

    def run_manual(self, max_rounds: int) -> ReconcileSupervisorReport:
        """Run manual reconciliation and return supervisor report."""
        return self._supervisor.run_manual(max_rounds=max_rounds)

    def status(self) -> ReconcileRuntimeStatus:
        """Return current runtime status snapshot."""
        last_report = self._supervisor.last_report
        return ReconcileRuntimeStatus(
            backlog_size=self._supervisor.backlog_size(),
            recent_reconcile_failures=self._supervisor.recent_reconcile_failures,
            dead_letter_count=self._supervisor.dead_letter_count(),
            last_trigger=(last_report.trigger if last_report is not None else None),
            last_executed=(last_report.executed if last_report is not None else None),
        )

    def readiness(self, *, recent_error_count: int = 0) -> OperationalReadinessReport:
        """Build operational readiness view from current supervisor metrics."""
        return build_operational_readiness_report(
            dependencies=self._dependencies,
            recent_error_count=recent_error_count,
            reconcile_backlog=self._supervisor.backlog_size(),
            recent_reconcile_failures=self._supervisor.recent_reconcile_failures,
            reconcile_backlog_threshold=self._reconcile_backlog_threshold,
        )
