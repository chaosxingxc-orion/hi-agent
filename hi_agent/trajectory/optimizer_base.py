"""Trajectory optimizer protocol."""

from __future__ import annotations

from typing import Protocol

from hi_agent.contracts import TrajectoryNode


class TrajectoryOptimizer(Protocol):
    """Optimizer behavior contract."""

    def select_next(
        self,
        current: TrajectoryNode,
        children: list[TrajectoryNode],
    ) -> TrajectoryNode | None:
        """Select next node to expand."""

    def backpropagate(
        self,
        leaf: TrajectoryNode,
        dag: dict[str, TrajectoryNode],
        decay: float = 0.9,
    ) -> None:
        """Backpropagate score from leaf to ancestors."""
