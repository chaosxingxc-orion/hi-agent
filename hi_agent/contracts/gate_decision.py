"""GateDecisionRequest contract: POST /gates/{gate_id}/decide.

Rule 12: carries tenant_id as a required field.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateDecisionRequest:
    """Request body for POST /gates/{gate_id}/decide.

    Fields
    ------
    gate_id:
        Identifier of the gate to decide on (also supplied in the URL path;
        repeated here for envelope completeness and auditing).
    run_id:
        The run this gate belongs to.
    tenant_id:
        Authenticated tenant.  Must be non-empty under research/prod posture.
    decision:
        One of ``"approved"`` or ``"rejected"``.
    reason:
        Human-readable rationale for the decision.
    decided_by:
        Identity of the actor who made the decision (user id or system label).
    decided_at:
        ISO 8601 timestamp of the decision.  If empty, the receiving handler
        stamps it at arrival time.
    """

    gate_id: str
    run_id: str
    tenant_id: str
    decision: str  # "approved" | "rejected"
    reason: str = ""
    decided_by: str = ""
    decided_at: str = ""  # ISO timestamp; handler stamps if empty

    # scope: process-internal boundary — validated in __post_init__ under strict posture
    _VALID_DECISIONS: frozenset[str] = field(
        default=frozenset({"approved", "rejected"}),
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if posture.is_strict and not self.tenant_id:
            raise ValueError(
                "GateDecisionRequest.tenant_id is required under research/prod posture"
            )
        if self.decision not in {"approved", "rejected"}:
            raise ValueError(
                f"GateDecisionRequest.decision must be 'approved' or 'rejected',"
                f" got {self.decision!r}"
            )
