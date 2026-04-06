"""Acceptance decision helpers for route outputs."""

from __future__ import annotations

from dataclasses import dataclass

from hi_agent.contracts import TaskContract, TrajectoryNode


@dataclass(frozen=True)
class AcceptanceResult:
    """Result for branch acceptance check."""

    accepted: bool
    reason: str


class AcceptancePolicy:
    """Simple acceptance policy for spike and MVP baseline."""

    def evaluate(self, contract: TaskContract, node: TrajectoryNode) -> AcceptanceResult:
        """Evaluate whether node outcome satisfies minimal acceptance signal."""
        if contract.acceptance_criteria and not node.description:
            return AcceptanceResult(accepted=False, reason="missing rationale")
        if node.local_score < 0.5:
            return AcceptanceResult(accepted=False, reason="score below threshold")
        return AcceptanceResult(accepted=True, reason="accepted")
