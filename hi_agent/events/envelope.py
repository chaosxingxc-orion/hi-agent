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
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""


def make_envelope(
    event_type: str,
    run_id: str,
    payload: dict,
    *,
    trace_id: str = "",
    span_id: str = "",
    parent_span_id: str = "",
) -> EventEnvelope:
    """Create envelope with UTC timestamp and optional trace context."""
    return EventEnvelope(
        event_type=event_type,
        run_id=run_id,
        payload=payload,
        timestamp=datetime.now(UTC).isoformat(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
    )
