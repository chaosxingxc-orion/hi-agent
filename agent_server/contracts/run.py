"""Run lifecycle contract types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunRequest:
    """Request to create and enqueue a new run."""

    tenant_id: str
    profile_id: str
    goal: str
    project_id: str = ""
    run_id: str = ""  # empty = auto-assigned
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResponse:
    """Response returned after run creation."""

    tenant_id: str
    run_id: str
    state: str
    current_stage: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunStatus:
    """Point-in-time status of a run."""

    tenant_id: str
    run_id: str
    state: str
    current_stage: str | None = None
    llm_fallback_count: int = 0
    finished_at: str | None = None


@dataclass(frozen=True)
class RunStream:
    """A single event in a run's SSE stream."""

    tenant_id: str
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    created_at: str = ""
