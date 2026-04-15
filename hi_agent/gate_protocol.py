"""Gate protocol types for Human Gate integration.

Provides GateEvent dataclass used by RunExecutor.register_gate() and
RunExecutor.resume() public APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


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
    opened_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
