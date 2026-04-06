"""JSONL-backed storage helpers for EventEnvelope."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from hi_agent.events.envelope import EventEnvelope


def append_event(path: str | Path, envelope: EventEnvelope) -> None:
    """Append a single event envelope to JSONL file."""
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    # Use explicit LF to keep line-delimited JSON consistent across platforms.
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(asdict(envelope), ensure_ascii=False) + "\n")


def append_events(path: str | Path, envelopes: Iterable[EventEnvelope]) -> None:
    """Append multiple event envelopes to JSONL file in input order."""
    event_path = Path(path)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        for envelope in envelopes:
            handle.write(json.dumps(asdict(envelope), ensure_ascii=False) + "\n")


def load_events(path: str | Path) -> tuple[list[EventEnvelope], int]:
    """Load envelopes from JSONL, skipping malformed lines and counting them."""
    event_path = Path(path)
    if not event_path.exists():
        return [], 0

    envelopes: list[EventEnvelope] = []
    bad_line_count = 0

    with event_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                envelopes.append(
                    EventEnvelope(
                        event_type=data["event_type"],
                        run_id=data["run_id"],
                        payload=data["payload"],
                        timestamp=data["timestamp"],
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                bad_line_count += 1

    return envelopes, bad_line_count


def load_events_for_run(path: str | Path, run_id: str) -> tuple[list[EventEnvelope], int]:
    """Load envelopes for a specific run_id and return malformed-line count."""
    envelopes, bad_line_count = load_events(path)
    return [envelope for envelope in envelopes if envelope.run_id == run_id], bad_line_count


def list_event_files(directory: str | Path) -> list[Path]:
    """List JSONL event files in a directory in sorted order."""
    directory_path = Path(directory)
    if not directory_path.exists():
        return []
    return sorted(path for path in directory_path.glob("*.jsonl") if path.is_file())
