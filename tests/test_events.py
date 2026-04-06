"""Tests for events subsystem."""

import pytest
from hi_agent.events import EventEmitter, validate_stage_state_payload


def test_event_emitter_records_event() -> None:
    """Emitter should store emitted envelope."""
    emitter = EventEmitter()
    envelope = emitter.emit("StageOpened", "run-1", {"stage_id": "S1"})

    assert envelope.event_type == "StageOpened"
    assert len(emitter.events) == 1


def test_payload_validator_rejects_missing_fields() -> None:
    """Schema validator should reject incomplete payloads."""
    with pytest.raises(ValueError):
        validate_stage_state_payload({"stage_id": "S1"})
