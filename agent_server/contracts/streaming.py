"""Streaming events contract types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True)
class EventCursor:
    """Pagination cursor for event log queries."""

    tenant_id: str
    run_id: str
    last_sequence: int
    page_size: int = 50


@dataclass(frozen=True)
class EventFilter:
    """Filter criteria for streaming event queries."""

    tenant_id: str
    run_id: str = ""
    trace_id: str = ""
    event_type: str = ""
    since_sequence: int = 0
