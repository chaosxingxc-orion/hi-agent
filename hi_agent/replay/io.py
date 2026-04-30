"""Replay I/O helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
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


class ReplayRecorder:
    """Append event envelopes to a JSONL file for later replay.

    Usage::

        recorder = ReplayRecorder(Path("events.jsonl"))
        recorder.record(envelope)
        recorder.close()

    The recorder lazily opens the file on the first ``record`` call and
    flushes each line immediately so that events survive crashes.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._handle = None  # type: ignore[assignment]  expiry_wave: Wave 27

    # -- public API --------------------------------------------------

    def record(self, envelope: EventEnvelope) -> None:
        """Append one event envelope as a JSON line."""
        if self._handle is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self._path.open("a", encoding="utf-8")
        line = json.dumps(asdict(envelope), ensure_ascii=False)
        self._handle.write(line + "\n")
        self._handle.flush()

    def close(self) -> None:
        """Flush and close the underlying file handle."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    @property
    def path(self) -> Path:
        """Return the path to the JSONL file."""
        return self._path

    # context-manager support
    def __enter__(self) -> ReplayRecorder:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
