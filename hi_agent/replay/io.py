"""Replay I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path

from hi_agent.events import EventEnvelope


def load_event_envelopes_jsonl(path: str | Path) -> list[EventEnvelope]:
    """Load event envelopes from a JSONL event file."""
    event_path = Path(path)
    envelopes: list[EventEnvelope] = []

    with event_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            data = json.loads(line)
            envelopes.append(
                EventEnvelope(
                    event_type=data["event_type"],
                    run_id=data["run_id"],
                    payload=data["payload"],
                    timestamp=data["timestamp"],
                )
            )

    return envelopes
