"""Audit event emitter for hi-agent (HI-W1-D2-001).

Appends structured audit events to .hi_agent/audit/events.jsonl so that
explicit policy decisions (e.g. evolve enabled in prod) are observable
without requiring a full observability stack.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def emit(event_name: str, payload: dict) -> None:
    """Append an audit event to .hi_agent/audit/events.jsonl.

    Args:
        event_name: Short identifier for the event type, e.g.
            "evolve.explicit_on_in_prod".
        payload: Arbitrary key-value metadata to include in the event record.
    """
    audit_dir = Path(".hi_agent/audit")
    audit_dir.mkdir(parents=True, exist_ok=True)
    event = {"event": event_name, "timestamp": time.time(), **payload}
    with open(audit_dir / "events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
