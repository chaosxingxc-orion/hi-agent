"""Task handle: the operational unit for task scheduling.

Each node in the TrajectoryGraph becomes a TaskHandle when scheduled.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class InvalidTransitionError(ValueError):
    """Raised when a task status transition is not allowed."""

    pass


class TaskStatus(Enum):
    """TaskStatus class."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"  # waiting for dependency
    YIELDED = "yielded"  # session yielded, waiting for resume
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Legal state transition matrix
_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.BLOCKED,
        TaskStatus.YIELDED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.BLOCKED: {TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.YIELDED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),  # terminal
    TaskStatus.FAILED: set(),  # terminal
    TaskStatus.CANCELLED: set(),  # terminal
}


@dataclass
class TaskHandle:
    """Operational handle for a scheduled task."""

    task_id: str
    node_id: str  # corresponding TrajectoryGraph node
    status: TaskStatus = TaskStatus.PENDING
    # Dependencies
    dependencies: list[str] = field(default_factory=list)  # task_ids this depends on
    dependents: list[str] = field(default_factory=list)  # task_ids depending on this
    blocked_by: list[str] = field(default_factory=list)  # currently blocking task_ids
    # Execution state
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    # Session yield/resume
    session_snapshot: dict[str, Any] | None = None  # saved when yielded
    yield_reason: str = ""
    # Timing
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    # Metrics
    tokens_used: int = 0
    execution_ms: int = 0
    # Execute function (optional per-task override)
    _execute_fn: Any = field(default=None, repr=False)
    # Thread-safe state transition
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def is_terminal(self) -> bool:
        """Return True if the task is in a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    def is_blocked(self) -> bool:
        """Return True if the task is blocked or yielded."""
        return self.status in (TaskStatus.BLOCKED, TaskStatus.YIELDED)

    def transition_to(self, new_status: TaskStatus) -> None:
        """Transition to a new status if the transition is valid.

        Args:
            new_status: The target TaskStatus.

        Raises:
            InvalidTransitionError: If the transition is not allowed.
        """
        with self._lock:
            allowed = _VALID_TRANSITIONS.get(self.status, set())
            if new_status not in allowed:
                raise InvalidTransitionError(f"Cannot transition {self.status!r} → {new_status!r}")
            self.status = new_status
