"""Streaming events contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.streaming")


@dataclass(frozen=True)
class Event:
    """A single structured event in the event stream."""

    tenant_id: str
    run_id: str
    event_type: str
    trace_id: str = ""
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
                f"Event constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "event_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class EventCursor:
    """Pagination cursor for event log queries."""

    tenant_id: str
    run_id: str
    last_sequence: int
    page_size: int = 50

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
                f"EventCursor constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "event_cursor_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class EventFilter:
    """Filter criteria for streaming event queries."""

    tenant_id: str
    run_id: str = ""
    trace_id: str = ""
    event_type: str = ""
    since_sequence: int = 0

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"EventFilter constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "event_filter_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
