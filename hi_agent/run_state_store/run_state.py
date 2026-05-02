"""Run state snapshot and persistence store."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunStateSnapshot:
    """Minimal persisted run state."""

    run_id: str
    current_stage: str
    stage_states: dict[str, str]
    action_seq: int
    task_views_count: int
    result: str | None
    fallback_events: list[dict[str, Any]] = field(default_factory=list)
    """Rule 14: fallback/degradation events recorded during the run.  Empty
    list means no degraded path was taken."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunStateSnapshot:
        """Deserialize snapshot from dict."""
        raw_events = payload.get("fallback_events") or []
        events: list[dict[str, Any]] = []
        if isinstance(raw_events, list):
            for entry in raw_events:
                if isinstance(entry, dict):
                    events.append(dict(entry))
        return cls(
            run_id=str(payload["run_id"]),
            current_stage=str(payload["current_stage"]),
            stage_states={str(k): str(v) for k, v in dict(payload["stage_states"]).items()},
            action_seq=int(payload["action_seq"]),
            task_views_count=int(payload["task_views_count"]),
            result=str(payload["result"]) if payload.get("result") is not None else None,
            fallback_events=events,
        )


class RunStateStore:
    """Run state store with in-memory cache and optional JSON file persistence."""

    def __init__(self, *, file_path: Path | str | None = None) -> None:
        """Initialize store."""
        self._file_path = Path(file_path) if file_path is not None else None
        self._snapshots: dict[str, RunStateSnapshot] = {}
        if self._file_path is not None:
            self._snapshots.update(self._read_file())

    def save(self, snapshot: RunStateSnapshot) -> None:
        """Persist snapshot to memory and optional JSON file."""
        self._snapshots[snapshot.run_id] = snapshot
        if self._file_path is not None:
            self._write_file()

    def get(self, run_id: str) -> RunStateSnapshot | None:
        """Get snapshot by run ID."""
        snapshot = self._snapshots.get(run_id)
        if snapshot is not None:
            return snapshot
        if self._file_path is None:
            return None
        self._snapshots.update(self._read_file())
        return self._snapshots.get(run_id)

    def _read_file(self) -> dict[str, RunStateSnapshot]:
        """Read snapshots from disk.

        Returns:
            dict[str, RunStateSnapshot]: Parsed snapshots, or an empty dict when
            the file is missing, empty, or malformed.
        """
        assert self._file_path is not None
        if not self._file_path.exists():
            return {}
        try:
            raw = self._file_path.read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
            return {
                str(run_id): RunStateSnapshot.from_dict(snapshot_payload)
                for run_id, snapshot_payload in dict(payload).items()
            }
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            return {}

    def _write_file(self) -> None:
        """Write snapshots to disk using atomic replace semantics."""
        assert self._file_path is not None
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            run_id: snapshot.to_dict() for run_id, snapshot in sorted(self._snapshots.items())
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._file_path.parent,
                prefix=f".{self._file_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(serialized)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)

            os.replace(temp_path, self._file_path)
        finally:
            if temp_path is not None and temp_path.exists():
                with suppress(OSError):
                    temp_path.unlink()
