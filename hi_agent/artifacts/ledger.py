"""Durable artifact ledger backed by JSONL append-only file."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from hi_agent.artifacts.contracts import Artifact

_logger = logging.getLogger(__name__)


class ArtifactLedger:
    """Durable append-only artifact ledger.

    Each artifact is written as a JSON line immediately on registration.
    The file is fsync'd after each write to survive sudden process death.
    Reads replay the full file.

    Thread-safe for concurrent in-process writers.
    """

    def __init__(self, ledger_path: str | Path) -> None:
        self._path = Path(ledger_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._store: dict[str, Artifact] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for offset, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    artifact = Artifact.from_dict(data)
                    self._store[artifact.artifact_id] = artifact
                except Exception:
                    # --- TE-1: quarantine + metric + log; skip but do not abort startup ---
                    preview = line[:120] if len(line) > 120 else line
                    _logger.warning(
                        "ArtifactLedger._load: corrupt line at offset %d in %s — "
                        "quarantining. preview=%r",
                        offset,
                        self._path,
                        preview,
                    )
                    quarantine_path = Path(str(self._path) + ".quarantine.jsonl")
                    try:
                        with quarantine_path.open("a", encoding="utf-8") as qf:
                            qf.write(line + "\n" if not line.endswith("\n") else line)
                    except Exception as qe:  # quarantine write failure must not crash load
                        _logger.warning(
                            "ArtifactLedger._load: failed to write quarantine file %s: %s",
                            quarantine_path,
                            qe,
                        )
                    try:
                        from hi_agent.observability.collector import get_metrics_collector

                        collector = get_metrics_collector()
                        if collector is not None:
                            collector.increment("hi_agent_artifact_corrupt_line_total")
                    except Exception:  # metrics must never crash callers
                        pass

    def register(self, artifact: Artifact) -> None:
        """Persist artifact to the ledger and update in-memory index."""
        with self._lock:
            self._store[artifact.artifact_id] = artifact
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(artifact.to_dict(), default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def store(self, artifact: Artifact) -> None:
        """Alias for register() — satisfies ArtifactRegistry interface."""
        self.register(artifact)

    def get(self, artifact_id: str) -> Artifact | None:
        """Retrieve an artifact by ID."""
        return self._store.get(artifact_id)

    def list(self, artifact_type: str | None = None) -> list[Artifact]:
        """Return all artifacts, optionally filtered by type."""
        items = list(self._store.values())
        if artifact_type:
            items = [a for a in items if a.artifact_type == artifact_type]
        return items

    def all(self) -> list[Artifact]:
        """Return all stored artifacts."""
        return list(self._store.values())

    def query(
        self,
        *,
        artifact_type: str | None = None,
        producer_action_id: str | None = None,
    ) -> list[Artifact]:
        """Query artifacts with optional type and producer filters (ArtifactRegistry compat)."""
        results = list(self._store.values())
        if artifact_type is not None:
            results = [a for a in results if a.artifact_type == artifact_type]
        if producer_action_id is not None:
            results = [a for a in results if a.producer_action_id == producer_action_id]
        return results

    def find_by_producer_run(self, run_id: str) -> list[Artifact]:
        """Return artifacts produced by a specific run."""
        return [a for a in self._store.values() if a.producer_run_id == run_id]

    def find_by_capability(self, capability_name: str) -> list[Artifact]:
        """Return artifacts produced by a specific capability."""
        return [a for a in self._store.values() if a.producer_capability == capability_name]

    def find_by_project(self, project_id: str) -> list[Artifact]:
        """Return artifacts belonging to a specific project."""
        return [a for a in self._store.values() if a.project_id == project_id]
