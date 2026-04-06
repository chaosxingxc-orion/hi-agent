"""Feedback collection and strategy recommendation for task decomposition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from hi_agent.task_decomposition.executor import DAGResult


@dataclass
class FeedbackRecord:
    """A single decomposition feedback record.

    Attributes:
        task_family: The task family that was decomposed.
        strategy: Decomposition strategy used (``"linear"``, ``"dag"``,
            ``"tree"``).
        success: Whether the DAG execution succeeded.
        parallelism_ratio: Ratio of parallel groups to total nodes.
        total_steps: Number of execution steps taken.
        failure_rate: Fraction of nodes that failed.
        timestamp: ISO-8601 timestamp when the record was created.
    """

    task_family: str
    strategy: str
    success: bool
    parallelism_ratio: float
    total_steps: int
    failure_rate: float
    timestamp: str


class DecompositionFeedback:
    """Collects feedback from DAG execution to optimise future decompositions.

    Tracks:
    - Which decomposition strategies work for which task families.
    - Average parallelism achieved.
    - Failure patterns at decomposition level.
    """

    def __init__(self) -> None:
        self._records: list[FeedbackRecord] = []

    def record(
        self, task_family: str, strategy: str, result: DAGResult
    ) -> None:
        """Record a feedback observation from a completed DAG execution.

        Args:
            task_family: The task family identifier.
            strategy: The decomposition strategy that was used.
            result: The DAGResult from the executor.
        """
        total = len(result.completed_nodes) + len(result.failed_nodes) + len(
            result.rolled_back_nodes
        )
        total = max(total, 1)  # prevent division by zero
        failure_rate = len(result.failed_nodes) / total
        parallelism_ratio = 0.0
        if result.total_steps > 0 and total > 0:
            parallelism_ratio = min(1.0, total / max(result.total_steps, 1))

        rec = FeedbackRecord(
            task_family=task_family,
            strategy=strategy,
            success=result.success,
            parallelism_ratio=parallelism_ratio,
            total_steps=result.total_steps,
            failure_rate=failure_rate,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._records.append(rec)

    def recommend_strategy(self, task_family: str) -> str:
        """Recommend best decomposition strategy based on historical data.

        Picks the strategy with the highest success rate for the given
        task family.  Falls back to ``"linear"`` when there is no data.

        Args:
            task_family: The task family to get a recommendation for.

        Returns:
            The recommended strategy string.
        """
        family_records = [
            r for r in self._records if r.task_family == task_family
        ]
        if not family_records:
            return "linear"

        # Group by strategy, compute success rate.
        strategy_stats: dict[str, list[bool]] = {}
        for rec in family_records:
            strategy_stats.setdefault(rec.strategy, []).append(rec.success)

        best_strategy = "linear"
        best_rate = -1.0
        for strat, outcomes in sorted(strategy_stats.items()):
            rate = sum(outcomes) / len(outcomes)
            if rate > best_rate:
                best_rate = rate
                best_strategy = strat

        return best_strategy

    def get_stats(self, task_family: str | None = None) -> dict[str, Any]:
        """Return aggregated statistics.

        Args:
            task_family: If provided, filter to this family. Otherwise
                return stats across all families.

        Returns:
            Dictionary with keys ``total_records``, ``success_rate``,
            ``avg_parallelism``, ``avg_failure_rate``, ``strategies``.
        """
        records = self._records
        if task_family is not None:
            records = [r for r in records if r.task_family == task_family]

        if not records:
            return {
                "total_records": 0,
                "success_rate": 0.0,
                "avg_parallelism": 0.0,
                "avg_failure_rate": 0.0,
                "strategies": {},
            }

        success_count = sum(1 for r in records if r.success)
        strategies: dict[str, int] = {}
        for r in records:
            strategies[r.strategy] = strategies.get(r.strategy, 0) + 1

        return {
            "total_records": len(records),
            "success_rate": success_count / len(records),
            "avg_parallelism": sum(r.parallelism_ratio for r in records)
            / len(records),
            "avg_failure_rate": sum(r.failure_rate for r in records)
            / len(records),
            "strategies": strategies,
        }
