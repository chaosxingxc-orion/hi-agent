"""SQLite-backed run store for durable run state persistence.

Survives process restarts.  Uses WAL mode and a threading.Lock for
thread safety, following the same pattern as SqliteEvidenceStore.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunRecord:
    """Persistent record for a single run."""

    run_id: str
    tenant_id: str
    task_contract_json: str  # serialized TaskContract
    status: str  # "queued" | "running" | "completed" | "failed" | "cancelled"
    priority: int
    attempt_count: int
    cancellation_flag: bool
    result_summary: str  # empty until complete
    error_summary: str
    created_at: float
    updated_at: float
    user_id: str = "__legacy__"  # workspace owner; "__legacy__" for pre-migration rows
    session_id: str = "__legacy__"  # workspace session; "__legacy__" for pre-migration rows


class SQLiteRunStore:
    """SQLite-backed store for durable run records.

    Thread-safe via ``check_same_thread=False`` plus an explicit
    ``threading.Lock`` that serializes all writes.
    """

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS run_records (
    run_id              TEXT    PRIMARY KEY,
    tenant_id           TEXT    NOT NULL DEFAULT '',
    user_id             TEXT    NOT NULL DEFAULT '__legacy__',
    session_id          TEXT    NOT NULL DEFAULT '__legacy__',
    task_contract_json  TEXT    NOT NULL DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'queued',
    priority            INTEGER NOT NULL DEFAULT 5,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    cancellation_flag   INTEGER NOT NULL DEFAULT 0,
    result_summary      TEXT    NOT NULL DEFAULT '',
    error_summary       TEXT    NOT NULL DEFAULT '',
    created_at          REAL    NOT NULL,
    updated_at          REAL    NOT NULL
)
"""
    _CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_run_records_tenant_id
ON run_records (tenant_id)
"""

    _MIGRATE_RUN_RECORDS = """\
ALTER TABLE run_records ADD COLUMN user_id TEXT NOT NULL DEFAULT '__legacy__';
ALTER TABLE run_records ADD COLUMN session_id TEXT NOT NULL DEFAULT '__legacy__';
"""

    def __init__(
        self,
        db_path: str | Path = ".hi_agent/runs.db",
    ) -> None:
        """Open (or create) the run records database.

        Args:
            db_path: Filesystem path for the SQLite file.  Parent
                directories are created automatically.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_INDEX)
        self._conn.commit()
        self._migrate()

    # -- helpers -------------------------------------------------------------

    def _migrate(self) -> None:
        cx = self._conn
        cols = {row[1] for row in cx.execute("PRAGMA table_info(run_records)")}
        if "user_id" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN user_id TEXT NOT NULL DEFAULT '__legacy__'"
            )
        if "session_id" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN session_id TEXT NOT NULL DEFAULT '__legacy__'"
            )
        cx.commit()
        cx.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_records_workspace "
            "ON run_records (tenant_id, user_id, session_id, created_at)"
        )
        cx.commit()

    def _row_to_record(self, row: tuple) -> RunRecord:
        return RunRecord(
            run_id=row[0],
            tenant_id=row[1],
            user_id=row[2],
            session_id=row[3],
            task_contract_json=row[4],
            status=row[5],
            priority=row[6],
            attempt_count=row[7],
            cancellation_flag=bool(row[8]),
            result_summary=row[9],
            error_summary=row[10],
            created_at=row[11],
            updated_at=row[12],
        )

    # -- public API ----------------------------------------------------------

    def upsert(self, record: RunRecord) -> None:
        """Insert or replace a run record.

        Args:
            record: The run record to persist.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO run_records "
                "(run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                "attempt_count, cancellation_flag, result_summary, error_summary, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.run_id,
                    record.tenant_id,
                    record.user_id,
                    record.session_id,
                    record.task_contract_json,
                    record.status,
                    record.priority,
                    record.attempt_count,
                    int(record.cancellation_flag),
                    record.result_summary,
                    record.error_summary,
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()

    def get(self, run_id: str) -> RunRecord | None:
        """Retrieve a run record by run_id.

        Args:
            run_id: Identifier of the run.

        Returns:
            The RunRecord or None if not found.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                "attempt_count, cancellation_flag, result_summary, error_summary, "
                "created_at, updated_at "
                "FROM run_records WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def list_by_tenant(self, tenant_id: str) -> list[RunRecord]:
        """Return all run records for a tenant.

        Args:
            tenant_id: Tenant whose runs to retrieve.

        Returns:
            List of RunRecord instances ordered by created_at ascending.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                "attempt_count, cancellation_flag, result_summary, error_summary, "
                "created_at, updated_at "
                "FROM run_records WHERE tenant_id = ? ORDER BY created_at ASC",
                (tenant_id,),
            )
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_by_workspace(
        self, run_id: str, tenant_id: str, user_id: str, session_id: str
    ) -> RunRecord | None:
        """Retrieve a run record filtered by workspace (tenant, user, session).

        Args:
            run_id: Identifier of the run.
            tenant_id: Tenant filter.
            user_id: User filter.
            session_id: Session filter.

        Returns:
            The RunRecord or None if not found or not owned by the given workspace.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                "attempt_count, cancellation_flag, result_summary, error_summary, "
                "created_at, updated_at "
                "FROM run_records WHERE run_id=? AND tenant_id=? AND user_id=? AND session_id=?",
                (run_id, tenant_id, user_id, session_id),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_by_workspace(
        self, tenant_id: str, user_id: str, session_id: str | None = None
    ) -> list[RunRecord]:
        """Return all run records for a workspace, ordered by created_at descending.

        Args:
            tenant_id: Tenant filter.
            user_id: User filter.
            session_id: Optional session filter; if omitted, returns all sessions.

        Returns:
            List of RunRecord instances.
        """
        with self._lock:
            if session_id:
                rows = self._conn.execute(
                    "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                    "attempt_count, cancellation_flag, result_summary, error_summary, "
                    "created_at, updated_at "
                    "FROM run_records WHERE tenant_id=? AND user_id=? AND session_id=? ORDER BY created_at DESC",
                    (tenant_id, user_id, session_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                    "attempt_count, cancellation_flag, result_summary, error_summary, "
                    "created_at, updated_at "
                    "FROM run_records WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
                    (tenant_id, user_id),
                ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def mark_cancelled(self, run_id: str) -> None:
        """Set status=cancelled and cancellation_flag=True.

        Args:
            run_id: Identifier of the run.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE run_records "
                "SET status = 'cancelled', cancellation_flag = 1, updated_at = ? "
                "WHERE run_id = ?",
                (now, run_id),
            )
            self._conn.commit()

    def mark_complete(self, run_id: str, result_summary: str) -> None:
        """Set status=completed and store result_summary.

        Args:
            run_id: Identifier of the run.
            result_summary: Human-readable or serialized run result.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE run_records "
                "SET status = 'completed', result_summary = ?, updated_at = ? "
                "WHERE run_id = ?",
                (result_summary, now, run_id),
            )
            self._conn.commit()

    def mark_failed(self, run_id: str, error_summary: str) -> None:
        """Set status=failed and store error_summary.

        Args:
            run_id: Identifier of the run.
            error_summary: Error description.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE run_records "
                "SET status = 'failed', error_summary = ?, updated_at = ? "
                "WHERE run_id = ?",
                (error_summary, now, run_id),
            )
            self._conn.commit()

    def is_cancelled(self, run_id: str) -> bool:
        """Return True if the run's cancellation_flag is set.

        Args:
            run_id: Identifier of the run.

        Returns:
            True if the run exists and cancellation_flag is True, else False.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT cancellation_flag FROM run_records WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return False
        return bool(row[0])

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
