"""Event envelope structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class EventEnvelope:
    """Canonical event envelope."""

    event_type: str
    run_id: str
    payload: dict
    timestamp: str


def make_envelope(event_type: str, run_id: str, payload: dict) -> EventEnvelope:
    """Create envelope with UTC timestamp."""
    return EventEnvelope(
        event_type=event_type,
        run_id=run_id,
        payload=payload,
        timestamp=datetime.now(UTC).isoformat(),
    )
