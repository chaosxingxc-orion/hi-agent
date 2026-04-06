"""Payload schema validators."""

from __future__ import annotations


def validate_stage_state_payload(payload: dict) -> None:
    """Validate stage-state event payload shape.

    Raises:
      ValueError: When mandatory fields are missing.
    """
    required = {"stage_id", "from_state", "to_state"}
    missing = required - set(payload.keys())
    if missing:
        missing_text = ",".join(sorted(missing))
        raise ValueError(f"Missing payload fields: {missing_text}")
