"""Aggregate sub-task results into a final orchestrator output."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.orchestrator.task_orchestrator import OrchestratorResult

from hi_agent.orchestrator.task_orchestrator import SubTaskResult


class ResultAggregator:
    """Aggregates results from sub-task execution into final output.

    Combines outputs from all completed sub-tasks,
    reports failures, and determines overall success.
    """

    def __init__(self) -> None:
        self._results: dict[str, SubTaskResult] = {}

    def record(self, node_id: str, result: SubTaskResult) -> None:
        """Record a sub-task result.

        Args:
            node_id: The DAG node identifier.
            result: The sub-task result to record.
        """
        self._results[node_id] = result

    def aggregate(self, task_id: str, strategy: str | None) -> OrchestratorResult:
        """Build final :class:`OrchestratorResult` from all recorded sub-task results.

        Args:
            task_id: Top-level task identifier.
            strategy: Decomposition strategy that was used.

        Returns:
            An :class:`OrchestratorResult` summarising the execution.
        """
        from hi_agent.orchestrator.task_orchestrator import OrchestratorResult

        failed = self.get_failed()
        success = len(failed) == 0 and len(self._results) > 0
        return OrchestratorResult(
            success=success,
            task_id=task_id,
            strategy=strategy,
            sub_results=list(self._results.values()),
        )

    def get_completed(self) -> list[SubTaskResult]:
        """Return sub-task results with outcome ``'completed'``."""
        return [r for r in self._results.values() if r.outcome == "completed"]

    def get_failed(self) -> list[SubTaskResult]:
        """Return sub-task results with outcome ``'failed'``."""
        return [r for r in self._results.values() if r.outcome == "failed"]

    def success_rate(self) -> float:
        """Return fraction of completed sub-tasks (0.0 when empty)."""
        total = len(self._results)
        if total == 0:
            return 0.0
        return len(self.get_completed()) / total
