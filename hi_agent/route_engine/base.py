"""Base protocol for route engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BranchProposal:
    """A branch proposal emitted by route engine."""

    branch_id: str
    rationale: str
    action_kind: str


class RouteEngine(Protocol):
    """Route engine behavior contract."""

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        """Propose one or more branches for current stage."""

