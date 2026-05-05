"""Run lifecycle contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.run")


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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness.

        Posture-aware: research/prod fail closed; dev warns.
        """
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.profile_id:
            missing.append("profile_id")
        if not self.goal:
            missing.append("goal")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"RunRequest constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "run_request_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not self.state:
            missing.append("state")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"RunResponse constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "run_response_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class RunStatus:
    """Point-in-time status of a run."""

    tenant_id: str
    run_id: str
    state: str
    current_stage: str | None = None
    llm_fallback_count: int = 0
    finished_at: str | None = None

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not self.state:
            missing.append("state")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"RunStatus constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "run_status_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class RunStream:
    """A single event in a run's SSE stream."""

    tenant_id: str
    run_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not self.event_type:
            missing.append("event_type")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"RunStream constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "run_stream_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
