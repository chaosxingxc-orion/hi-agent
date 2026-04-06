"""Run lifecycle contracts."""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    """Lifecycle states for a durable run entity."""

    CREATED = "created"
    ACTIVE = "active"
    WAITING = "waiting"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
