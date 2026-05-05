"""Pause/resume gate contract types."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

# W31-N (N.5): posture-strict values mirror
# :class:`hi_agent.config.posture.Posture.is_strict` semantics. Resolved
# from HI_AGENT_POSTURE so this module does NOT import hi_agent.
_STRICT_POSTURE_VALUES = frozenset({"research", "prod"})


def _posture_is_strict() -> bool:
    return os.environ.get("HI_AGENT_POSTURE", "dev").lower() in _STRICT_POSTURE_VALUES


_LOGGER = logging.getLogger("agent_server.contracts.gate")


@dataclass(frozen=True)
class PauseToken:
    """Token emitted when a run pauses, required to resume."""

    tenant_id: str
    run_id: str
    token: str
    reason: str = ""
    emitted_at: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"PauseToken constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "pause_token_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class ResumeRequest:
    """Request to resume a paused run."""

    tenant_id: str
    run_id: str
    pause_token: str
    input_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"ResumeRequest constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "resume_request_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class GateEvent:
    """Event record for a pause or resume action."""

    tenant_id: str
    run_id: str
    event_type: str  # "paused" | "resumed"
    token: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.run_id:
            missing.append("run_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"GateEvent constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "gate_event_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass
class GateDecisionRequest:
    """Request body for POST /gates/{gate_id}/decide.

    W31-N (N.5): re-declared under ``agent_server.contracts.gate`` so the
    route handler can construct it without importing
    :mod:`hi_agent.contracts.gate_decision` (R-AS-1). Field set is
    identical to the hi_agent counterpart so downstream tooling that
    reads the request body sees no schema change.

    Fields
    ------
    gate_id:
        Identifier of the gate to decide on (also supplied in the URL
        path; repeated here for envelope completeness and auditing).
    run_id:
        The run this gate belongs to.
    tenant_id:
        Authenticated tenant. Must be non-empty under research/prod
        posture.
    decision:
        One of ``"approved"`` or ``"rejected"``.
    reason:
        Human-readable rationale for the decision.
    decided_by:
        Identity of the actor who made the decision.
    decided_at:
        ISO 8601 timestamp; the receiving handler stamps it if empty.
    """

    gate_id: str
    run_id: str
    tenant_id: str
    decision: str  # "approved" | "rejected"
    reason: str = ""
    decided_by: str = ""
    decided_at: str = ""

    def __post_init__(self) -> None:
        if _posture_is_strict() and not self.tenant_id:
            raise ValueError(
                "GateDecisionRequest.tenant_id is required under research/prod posture"
            )
        if self.decision not in {"approved", "rejected"}:
            raise ValueError(
                f"GateDecisionRequest.decision must be 'approved' or 'rejected',"
                f" got {self.decision!r}"
            )
