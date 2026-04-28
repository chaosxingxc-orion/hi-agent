"""Durable artifact ledger backed by JSONL append-only file."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from hi_agent.artifacts.contracts import Artifact
from hi_agent.artifacts.metrics import (
    legacy_tenantless_denied_total,
    legacy_tenantless_visible_total,
)

_logger = logging.getLogger(__name__)


def _resolve_ledger_path(ledger_path: str | Path | None) -> Path | None:
    """Resolve the ledger file path applying posture-aware defaults (TE-2).

    - Under research/prod posture: a path must be available.  If ``ledger_path``
      is ``None``, ``HI_AGENT_DATA_DIR`` is consulted.  Missing both raises
      ``ValueError``.
    - Under dev posture: ``None`` is accepted; returns ``None`` (in-memory mode).
    """
    if ledger_path is not None:
        return Path(ledger_path)

    from hi_agent.config.posture import Posture

    posture = Posture.from_env()
    if posture.requires_durable_ledger:
        data_dir = os.environ.get("HI_AGENT_DATA_DIR", "").strip()
        if not data_dir:
            raise ValueError(
                "ArtifactLedger requires HI_AGENT_DATA_DIR under research/prod posture"
            )
        return Path(data_dir) / "artifacts.jsonl"

    # Dev posture with no path: in-memory mode.
    return None


class ArtifactLedger:
    """Durable append-only artifact ledger.

    Each artifact is written as a JSON line immediately on registration.
    The file is fsync'd after each write to survive sudden process death.
    Reads replay the full file.

    When constructed with ``ledger_path=None`` under dev posture the ledger
    operates in in-memory mode (no file backing).  Under research/prod posture
    a path is always required (see :func:`_resolve_ledger_path`).

    Thread-safe for concurrent in-process writers.
    """

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self._path: Path | None = _resolve_ledger_path(ledger_path)
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._store: dict[str, Artifact] = {}
        self._load()

    def _load(self) -> None:
        if self._path is None:
            return
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
            if self._path is not None:
                # J2: path traversal guard — ledger path is controlled by
                # __init__ (derived from HI_AGENT_DATA_DIR or an explicit
                # constructor argument), so this is an internal consistency
                # check rather than an untrusted-input guard.
                from hi_agent.artifacts.storage import assert_within_workspace
                assert_within_workspace(self._path, self._path.parent)
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(artifact.to_dict(), default=str) + "\n")
                    f.flush()
                    os.fsync(f.fileno())

    def store(self, artifact: Artifact) -> None:
        """Alias for register() — satisfies ArtifactRegistry interface."""
        self.register(artifact)

    def get(self, artifact_id: str, *, tenant_id: str | None = None) -> Artifact | None:
        """Retrieve an artifact by ID, optionally filtered by tenant."""
        artifact = self._store.get(artifact_id)
        if artifact is None:
            return None
        if tenant_id is not None and tenant_id != "":
            art_tenant = getattr(artifact, "tenant_id", "")
            if art_tenant in (None, ""):
                return self._allow_legacy(artifact, tenant_id)
            if art_tenant != tenant_id:
                return None
        return artifact

    def list(self, artifact_type: str | None = None) -> list[Artifact]:
        """Return all artifacts, optionally filtered by type."""
        items = list(self._store.values())
        if artifact_type:
            items = [a for a in items if a.artifact_type == artifact_type]
        return items

    def all(self, *, tenant_id: str | None = None) -> list[Artifact]:
        """Return all stored artifacts, optionally filtered by tenant."""
        items = list(self._store.values())
        if tenant_id is None or tenant_id == "":
            return items
        return [a for a in items if self._tenant_visible(a, tenant_id)]

    def query(
        self,
        *,
        artifact_type: str | None = None,
        producer_action_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[Artifact]:
        """Query artifacts with optional type, producer, and tenant filters."""
        results = list(self._store.values())
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_visible(a, tenant_id)]
        if artifact_type is not None:
            results = [a for a in results if a.artifact_type == artifact_type]
        if producer_action_id is not None:
            results = [a for a in results if a.producer_action_id == producer_action_id]
        return results

    def query_by_source_ref(
        self, source_ref: str, *, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts referencing the given source ref, filtered by tenant."""
        # TODO: implement full source_ref indexing in Wave 12
        # (full index deferred; wave 11 deadline missed)
        results = [a for a in self._store.values() if source_ref in a.source_refs]
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_visible(a, tenant_id)]
        return results

    def query_by_upstream(
        self, upstream_id: str, *, tenant_id: str | None = None
    ) -> list[Artifact]:
        """Return all artifacts with upstream_id in upstream_artifact_ids, filtered by tenant."""
        # TODO: implement full upstream index in Wave 12
        # (full index deferred; wave 11 deadline missed)
        results = [
            a for a in self._store.values() if upstream_id in a.upstream_artifact_ids
        ]
        if tenant_id is not None and tenant_id != "":
            results = [a for a in results if self._tenant_visible(a, tenant_id)]
        return results

    def _allow_legacy(self, artifact: Artifact, requested_tenant: str) -> Artifact | None:
        """Apply posture-aware policy for legacy tenantless artifacts on get()."""
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if posture.is_strict:
            _logger.warning(
                "legacy tenantless artifact denied in strict posture: "
                "artifact_id=%s tenant_requested=%s",
                artifact.artifact_id,
                requested_tenant,
            )
            legacy_tenantless_denied_total.inc(posture=posture.value)
            return None
        _logger.debug(
            "legacy tenantless artifact visible in dev posture: artifact_id=%s",
            artifact.artifact_id,
        )
        legacy_tenantless_visible_total.inc(posture=posture.value)
        return artifact

    def _tenant_visible(self, artifact: Artifact, tenant_id: str) -> bool:
        """Return True if artifact is visible to the requesting tenant."""
        art_tenant = getattr(artifact, "tenant_id", "")
        if art_tenant in (None, ""):
            from hi_agent.config.posture import Posture

            posture = Posture.from_env()
            if posture.is_strict:
                _logger.warning(
                    "legacy tenantless artifact denied in strict posture: "
                    "artifact_id=%s tenant_requested=%s",
                    artifact.artifact_id,
                    tenant_id,
                )
                legacy_tenantless_denied_total.inc(posture=posture.value)
                return False
            _logger.debug(
                "legacy tenantless artifact visible in dev posture: artifact_id=%s",
                artifact.artifact_id,
            )
            legacy_tenantless_visible_total.inc(posture=posture.value)
            return True
        return art_tenant == tenant_id

    def find_by_producer_run(self, run_id: str) -> list[Artifact]:
        """Return artifacts produced by a specific run."""
        return [a for a in self._store.values() if a.producer_run_id == run_id]

    def find_by_capability(self, capability_name: str) -> list[Artifact]:
        """Return artifacts produced by a specific capability."""
        return [a for a in self._store.values() if a.producer_capability == capability_name]

    def find_by_project(self, project_id: str) -> list[Artifact]:
        """Return artifacts belonging to a specific project."""
        return [a for a in self._store.values() if a.project_id == project_id]
