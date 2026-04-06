"""Stage lifecycle contracts."""

from __future__ import annotations

from enum import StrEnum


class StageState(StrEnum):
    """Lifecycle states for a single stage in the TRACE pipeline."""

    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"

