"""Platform-level persistence record types.

These define the shape of durable audit records across execution, gates, and teams.
Persistence backends are wired separately per record type.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunLease:
    """Durable run lease held by a worker."""

    worker_id: str
    run_id: str
    expires_at: float  # epoch seconds
    project_id: str = ""


@dataclass
class StageCheckpoint:
    """Checkpoint of a stage's execution state."""

    run_id: str
    stage_id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    artifacts: list[str] = field(default_factory=list)  # artifact_ids
    memo: str = ""
    checkpointed_at: str = ""
    project_id: str = ""


@dataclass
class ActionAttempt:
    """Record of an attempted external action."""

    run_id: str
    stage_id: str
    action_id: str
    status: str  # "pending" | "completed" | "failed"
    started_at: str = ""
    ended_at: str = ""
    error: str = ""
    project_id: str = ""


@dataclass
class CancellationSignal:
    """Record of a cancellation signal issued for a run."""

    run_id: str
    issued_at: str
    issued_by: str
    reason: str = ""
    propagated_to: list[str] = field(default_factory=list)  # ["queue", "token", ...]
    project_id: str = ""
