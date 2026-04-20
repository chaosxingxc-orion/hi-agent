"""Run lifecycle contracts."""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    """Lifecycle states for a durable run entity.

    TRACE formal states (CREATED → ACTIVE → COMPLETED/FAILED/ABORTED) represent
    the run's lifecycle as tracked by the kernel.

    Operational states (RUNNING, CANCELLED, QUEUE_TIMEOUT, QUEUE_FULL) are
    emitted by the server-side RunManager and are visible via the API.  They
    are not part of the kernel state machine but are valid values on ManagedRun.
    """

    # --- TRACE formal states ---
    CREATED = "created"
    ACTIVE = "active"
    WAITING = "waiting"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    # --- RunManager operational states ---
    RUNNING = "running"  # actively executing in a worker thread
    CANCELLED = "cancelled"  # cancelled via DELETE /runs/{id}
    QUEUE_TIMEOUT = "queue_timeout"  # waited too long in queue for a concurrency slot
    QUEUE_FULL = "queue_full"  # queue capacity exceeded at submission time
