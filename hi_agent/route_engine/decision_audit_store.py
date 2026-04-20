"""Decision audit stores for route decision records."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class InMemoryDecisionAuditStore:
    """Append-only in-memory store for route decision audits.

    The store keeps insertion order stable to guarantee deterministic replay in
    tests and local workflows.
    """

    def __init__(self) -> None:
        """Initialize an empty append-only audit list."""
        self._items: list[dict[str, Any]] = []

    def append(self, audit: Mapping[str, Any]) -> dict[str, Any]:
        """Append one normalized audit record and return a defensive copy."""
        if not isinstance(audit, Mapping):
            raise TypeError("audit must be a mapping")
        run_id = self._normalize_required_str(audit.get("run_id"), "run_id")
        stage_id = self._normalize_required_str(audit.get("stage_id"), "stage_id")

        normalized = dict(audit)
        normalized["run_id"] = run_id
        normalized["stage_id"] = stage_id
        self._items.append(normalized)
        return dict(normalized)

    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return audits for one run in insertion order."""
        normalized_run_id = self._normalize_required_str(run_id, "run_id")
        return [dict(item) for item in self._items if item["run_id"] == normalized_run_id]

    def latest_by_stage(self, run_id: str, stage_id: str) -> dict[str, Any] | None:
        """Return latest audit for (run_id, stage_id), or ``None`` if missing."""
        normalized_run_id = self._normalize_required_str(run_id, "run_id")
        normalized_stage_id = self._normalize_required_str(stage_id, "stage_id")
        for item in reversed(self._items):
            if item["run_id"] == normalized_run_id and item["stage_id"] == normalized_stage_id:
                return dict(item)
        return None

    def _normalize_required_str(self, value: object, field: str) -> str:
        """Run _normalize_required_str."""
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a non-empty string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} must be a non-empty string")
        return normalized


class SqliteDecisionAuditStore:
    """SQLite-backed store for route decision audit records.

    Persists audit records to a SQLite database so they survive process
    restarts.  Thread-safe via ``check_same_thread=False`` and an internal
    threading lock.
    """

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS route_decision_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    stage_id     TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   REAL NOT NULL
)
"""
    _CREATE_INDEX_RUN = """\
CREATE INDEX IF NOT EXISTS idx_rda_run_id
ON route_decision_audit (run_id)
"""
    _CREATE_INDEX_STAGE = """\
CREATE INDEX IF NOT EXISTS idx_rda_run_stage
ON route_decision_audit (run_id, stage_id)
"""

    def __init__(self, db_path: str | Path = ".hi_agent/audit.db") -> None:
        """Open (or create) the audit database.

        Args:
            db_path: Filesystem path for the SQLite file.  Use ``":memory:"``
                for tests.  Parent directories are created automatically for
                file-backed paths.
        """
        self._db_path = db_path if db_path == ":memory:" else str(Path(db_path))
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_INDEX_RUN)
        self._conn.execute(self._CREATE_INDEX_STAGE)
        self._conn.commit()

    def append(self, audit: Mapping[str, Any]) -> dict[str, Any]:
        """Normalize and persist one audit record; return a defensive copy."""
        if not isinstance(audit, Mapping):
            raise TypeError("audit must be a mapping")
        run_id = self._normalize_required_str(audit.get("run_id"), "run_id")
        stage_id = self._normalize_required_str(audit.get("stage_id"), "stage_id")

        normalized = dict(audit)
        normalized["run_id"] = run_id
        normalized["stage_id"] = stage_id

        with self._lock:
            self._conn.execute(
                "INSERT INTO route_decision_audit "
                "(run_id, stage_id, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (run_id, stage_id, json.dumps(normalized), time.time()),
            )
            self._conn.commit()
        return dict(normalized)

    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Return all audit records for *run_id* in insertion order."""
        normalized_run_id = self._normalize_required_str(run_id, "run_id")
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM route_decision_audit WHERE run_id = ? ORDER BY id ASC",
                (normalized_run_id,),
            )
            rows = cur.fetchall()
        return [json.loads(row[0]) for row in rows]

    def latest_by_stage(self, run_id: str, stage_id: str) -> dict[str, Any] | None:
        """Return the most recent audit for *(run_id, stage_id)*, or ``None``."""
        normalized_run_id = self._normalize_required_str(run_id, "run_id")
        normalized_stage_id = self._normalize_required_str(stage_id, "stage_id")
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload_json FROM route_decision_audit "
                "WHERE run_id = ? AND stage_id = ? ORDER BY id DESC LIMIT 1",
                (normalized_run_id, normalized_stage_id),
            )
            row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def _normalize_required_str(self, value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a non-empty string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} must be a non-empty string")
        return normalized

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
