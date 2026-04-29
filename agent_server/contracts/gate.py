"""Pause/resume gate contract types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PauseToken:
    """Token emitted when a run pauses, required to resume."""

    tenant_id: str
    run_id: str
    token: str
    reason: str = ""
    emitted_at: str = ""


@dataclass(frozen=True)
class ResumeRequest:
    """Request to resume a paused run."""

    tenant_id: str
    run_id: str
    pause_token: str
    input_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateEvent:
    """Event record for a pause or resume action."""

    tenant_id: str
    run_id: str
    event_type: str  # "paused" | "resumed"
    token: str = ""
    created_at: str = ""
