"""Branch lifecycle contracts."""

from __future__ import annotations

from enum import StrEnum


class BranchState(StrEnum):
    """Lifecycle states for a trajectory branch."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    WAITING = "waiting"
    PRUNED = "pruned"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
