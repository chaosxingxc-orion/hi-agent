"""Event emitter implementation."""

from __future__ import annotations

from hi_agent.events.envelope import EventEnvelope, make_envelope


class EventEmitter:
    """In-memory event emitter for observability and testing."""

    def __init__(self) -> None:
        """Initialize in-memory event buffer."""
        self.events: list[EventEnvelope] = []

    def emit(self, event_type: str, run_id: str, payload: dict) -> EventEnvelope:
        """Emit one event and return envelope."""
        envelope = make_envelope(event_type=event_type, run_id=run_id, payload=payload)
        self.events.append(envelope)
        return envelope
