"""Gate protocol types for Human Gate integration.

Provides GateEvent dataclass used by RunExecutor.register_gate() and
RunExecutor.resume() public APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


class GatePendingError(Exception):
    """Raised when stage execution is attempted while a human gate is pending.

    Call :meth:`~hi_agent.runner.RunExecutor.resume` with the blocking
    gate_id before continuing execution.
    """

    def __init__(self, gate_id: str, message: str = "") -> None:
        """Initialise with the blocking gate_id and an optional custom message."""
        default_msg = f"Gate {gate_id!r} is pending — call resume() before continuing"
        super().__init__(message or default_msg)
        self.gate_id = gate_id


@dataclass
class GateEvent:
    """Record of a registered human gate point.

    Attributes:
        gate_id: Caller-assigned identifier for this gate.
        gate_type: One of contract_correction / route_direction /
            artifact_review / final_approval.
        phase_name: Stage or phase at which the gate was registered.
        recommendation: Optional suggestion surfaced to the human reviewer.
        output_summary: Brief description of the work product awaiting review.
        opened_at: ISO-8601 timestamp when the gate was registered.
    """

    gate_id: str
    gate_type: str = "final_approval"
    phase_name: str = ""
    recommendation: str = ""
    output_summary: str = ""
    opened_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
