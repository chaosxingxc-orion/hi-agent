"""SQLite-backed run store for durable run state persistence.

Survives process restarts.  Uses WAL mode and a threading.Lock for
thread safety, following the same pattern as SqliteEvidenceStore.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext

_logger = logging.getLogger("hi_agent.server.run_store")


class TenantScopeError(ValueError):
    """Raised when a research/prod-posture mutation is attempted without tenant_id.

    W34+ defense-in-depth: every mutating SQLiteRunStore method must be
    tenant-scoped under research/prod posture. The optional ``workspace`` /
    ``tenant_id`` parameter remains for dev-posture back-compat (warns +
    proceeds unscoped) but fails closed under research/prod.

    Mirrors the pattern landed at ``hi_agent/server/run_queue.py`` in W33-D.2.
    """


def _check_run_store_tenant_scope(workspace: str | None, *, method: str) -> str | None:
    """Posture-aware gate for SQLiteRunStore mutation methods (W34+ D.2-style).

    Under research/prod posture, missing workspace raises ``TenantScopeError``.
    Under dev posture, missing workspace emits a structured WARNING and
    returns ``None`` so the caller proceeds unscoped (back-compat).

    Returns the workspace string on the happy path so the caller can use
    ``effective = _check_run_store_tenant_scope(workspace, method=...)``.
    """
    if workspace is not None and workspace.strip():
        return workspace
    from hi_agent.config.posture import Posture

    posture = Posture.from_env()
    if posture.is_strict:
        raise TenantScopeError(
            f"SQLiteRunStore.{method} requires workspace (tenant_id) under "
            f"posture={posture.value}. Pass workspace=<tenant_id> to scope the "
            "mutation; defense-in-depth (W34+ D.2 mirror)."
        )
    _logger.warning(
        "run_store.%s: workspace=None under posture=%s; proceeding unscoped "
        "(dev back-compat). All callers should pass workspace=<tenant_id>.",
        method,
        posture.value,
    )
    return None


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
    project_id: str = ""  # project scope; empty for pre-migration / unscoped rows
    finished_at: float = 0.0  # 0 until terminal state; epoch seconds
    # W33-F: Rule 12 spine lineage fields (additive Optional, default empty for back-compat).
    # NOTE: ``attempt_count`` (above) is a counter; ``attempt_id`` is a stable
    # identifier per attempt (UUID4 or similar). Both can coexist.
    parent_run_id: str = ""  # parent run identifier (lineage; empty for root runs)
    attempt_id: str = ""  # stable identifier per attempt (UUID4 or similar)
    phase_id: str = ""  # TRACE phase tagging (e.g. "intake", "execute", "finalize")

    def __post_init__(self) -> None:
        """W34+ T2a: posture-aware spine validation at construction.

        Mirrors the W34-F.3 ReasoningTrace pattern: under research/prod the
        durable record MUST carry non-empty ``run_id`` and ``tenant_id``;
        empty values would persist a row that no tenant-scoped query can
        ever read back. Under dev posture the constraint relaxes to a
        WARNING so storage-layer reconstructions (``_row_to_record``) keep
        working when reading legacy rows that pre-date W33-F.
        """
        # Storage-layer reconstructions (``_row_to_record``) populate every
        # field from a SQL row — those rows always carry tenant_id NOT NULL
        # at the schema level and so satisfy the check trivially. The
        # validation matters most at fresh-construction sites in
        # ``RunManager.create_run`` and any new caller building a record
        # from a TaskContract.
        from hi_agent.config.posture import Posture
        posture = Posture.from_env()
        missing: list[str] = []
        if not self.run_id:
            missing.append("run_id")
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if posture.is_strict:
            raise ValueError(
                "RunRecord constructed without required spine fields under "
                f"posture={posture.value}: missing={missing}. Populate the "
                "fields at the construction site (Rule 12)."
            )
        # Dev posture: warn but allow the construction so reconstruction
        # paths keep working with legacy rows.
        import logging
        logging.getLogger("hi_agent.server.run_store").warning(
            "run_record_spine_incomplete: missing=%s posture=%s; would "
            "fail-closed under research/prod.",
            missing,
            posture.value,
        )


class SQLiteRunStore:
    """SQLite-backed store for durable run records.

    Thread-safe via ``check_same_thread=False`` plus an explicit
    ``threading.Lock`` that serializes all writes.
    """

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS run_records (
    run_id              TEXT    PRIMARY KEY,
    tenant_id           TEXT    NOT NULL,
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
    updated_at          REAL    NOT NULL,
    finished_at         REAL    NOT NULL DEFAULT 0,
    parent_run_id       TEXT    NOT NULL DEFAULT '',
    attempt_id          TEXT    NOT NULL DEFAULT '',
    phase_id            TEXT    NOT NULL DEFAULT ''
)
"""
    _CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_run_records_tenant_id
ON run_records (tenant_id)
"""

    _MIGRATE_RUN_RECORDS = """\
ALTER TABLE run_records ADD COLUMN user_id TEXT NOT NULL DEFAULT '__legacy__';
ALTER TABLE run_records ADD COLUMN session_id TEXT NOT NULL DEFAULT '__legacy__';
ALTER TABLE run_records ADD COLUMN parent_run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE run_records ADD COLUMN attempt_id TEXT NOT NULL DEFAULT '';
ALTER TABLE run_records ADD COLUMN phase_id TEXT NOT NULL DEFAULT '';
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
        # Track D C-1: WAL + busy_timeout via shared helper.
        from hi_agent._sqlite_init import configure_sqlite_connection
        configure_sqlite_connection(self._conn)
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
        if "project_id" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN project_id TEXT NOT NULL DEFAULT ''"
            )
        if "finished_at" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN finished_at REAL NOT NULL DEFAULT 0"
            )
        # W33-F: Rule 12 spine lineage fields. Idempotent — re-running on a
        # database that already has the columns is a no-op via the membership
        # check.
        if "parent_run_id" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN parent_run_id TEXT NOT NULL DEFAULT ''"
            )
        if "attempt_id" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN attempt_id TEXT NOT NULL DEFAULT ''"
            )
        if "phase_id" not in cols:
            cx.execute(
                "ALTER TABLE run_records ADD COLUMN phase_id TEXT NOT NULL DEFAULT ''"
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
            project_id=row[13],
            finished_at=row[14],
            parent_run_id=row[15],
            attempt_id=row[16],
            phase_id=row[17],
        )

    # -- public API ----------------------------------------------------------

    def upsert(self, record: RunRecord, *, exec_ctx: RunExecutionContext | None = None) -> None:
        """Insert or replace a run record.

        Args:
            record: The run record to persist.
            exec_ctx: Optional RunExecutionContext; when provided, spine fields
                (tenant_id, user_id, session_id, project_id, run_id) are
                derived from exec_ctx when the record's own fields are empty.
                Explicit record fields always take precedence over exec_ctx.
        """
        if exec_ctx is not None:
            if not record.tenant_id:
                record.tenant_id = exec_ctx.tenant_id
            if record.user_id in ("", "__legacy__"):
                record.user_id = exec_ctx.user_id or record.user_id
            if record.session_id in ("", "__legacy__"):
                record.session_id = exec_ctx.session_id or record.session_id
            if not record.project_id:
                record.project_id = exec_ctx.project_id
            if not record.run_id:
                record.run_id = exec_ctx.run_id
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO run_records "
                "(run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
                "attempt_count, cancellation_flag, result_summary, error_summary, "
                "created_at, updated_at, project_id, finished_at, "
                "parent_run_id, attempt_id, phase_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    record.project_id,
                    record.finished_at,
                    record.parent_run_id,
                    record.attempt_id,
                    record.phase_id,
                ),
            )
            self._conn.commit()

    def get(
        self,
        run_id: str,
        workspace: str | None = None,
    ) -> RunRecord | None:
        """Retrieve a run record by run_id.

        Args:
            run_id: Identifier of the run.
            workspace: Optional tenant workspace ID.  When provided, adds a
                ``WHERE … AND workspace_id = ?`` filter to prevent cross-tenant
                data leaks.
                # scope: process-internal — workspace scoping deferred, all callers must be audited

        Returns:
            The RunRecord or None if not found.
        """
        with self._lock:
            if workspace is not None:
                cur = self._conn.execute(
                    "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                    "status, priority, attempt_count, cancellation_flag, result_summary, "
                    "error_summary, created_at, updated_at, project_id, finished_at, "
                    "parent_run_id, attempt_id, phase_id "
                    "FROM run_records WHERE run_id = ? AND tenant_id = ?",
                    (run_id, workspace),
                )
            else:
                # scope: process-internal — workspace scoping deferred, all callers must be audited
                cur = self._conn.execute(
                    "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                    "status, priority, attempt_count, cancellation_flag, result_summary, "
                    "error_summary, created_at, updated_at, project_id, finished_at, "
                    "parent_run_id, attempt_id, phase_id "
                    "FROM run_records WHERE run_id = ?",
                    (run_id,),
                )
            row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def get_for_tenant(self, run_id: str, workspace: str | None) -> RunRecord | None:
        """Retrieve a run record, REQUIRING a tenant workspace filter.

        Unlike ``get()``, this method hard-errors when ``workspace`` is None
        to prevent accidentally bypassing tenant isolation.

        Args:
            run_id: Identifier of the run.
            workspace: Required tenant workspace ID.

        Returns:
            The RunRecord if it exists and belongs to the given tenant, else None.

        Raises:
            ValueError: If ``workspace`` is None.
        """
        if workspace is None:
            raise ValueError(
                "get_for_tenant requires a non-None workspace; "
                "use get() for process-internal lookups (all callers must be audited)"
            )
        return self.get(run_id, workspace=workspace)

    def list_by_tenant(self, tenant_id: str) -> list[RunRecord]:
        """Return all run records for a tenant.

        Args:
            tenant_id: Tenant whose runs to retrieve.

        Returns:
            List of RunRecord instances ordered by created_at ascending.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                "status, priority, attempt_count, cancellation_flag, result_summary, "
                "error_summary, created_at, updated_at, project_id, finished_at, "
                "parent_run_id, attempt_id, phase_id "
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
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                "status, priority, attempt_count, cancellation_flag, result_summary, "
                "error_summary, created_at, updated_at, project_id, finished_at, "
                "parent_run_id, attempt_id, phase_id "
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
                    "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                    "status, priority, attempt_count, cancellation_flag, result_summary, "
                    "error_summary, created_at, updated_at, project_id, finished_at, "
                    "parent_run_id, attempt_id, phase_id "
                    "FROM run_records WHERE tenant_id=? AND user_id=? AND session_id=? "
                    "ORDER BY created_at DESC",
                    (tenant_id, user_id, session_id),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                    "status, priority, attempt_count, cancellation_flag, result_summary, "
                    "error_summary, created_at, updated_at, project_id, finished_at, "
                    "parent_run_id, attempt_id, phase_id "
                    "FROM run_records WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
                    (tenant_id, user_id),
                ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def mark_cancelled(self, run_id: str, workspace: str | None = None) -> None:
        """Set status=cancelled and cancellation_flag=True.

        W34+ D.2 mirror: the optional ``workspace`` (tenant_id) is required
        under research/prod posture and warns under dev. Cross-tenant mutation
        is structurally impossible once the call site is migrated to pass it.

        Args:
            run_id: Identifier of the run.
            workspace: Optional tenant workspace ID. Required under research/
                prod; dev back-compat allows None with a logged warning.
        """
        effective = _check_run_store_tenant_scope(workspace, method="mark_cancelled")
        now = time.time()
        with self._lock:
            if effective is not None:
                self._conn.execute(
                    "UPDATE run_records "
                    "SET status = 'cancelled', cancellation_flag = 1, updated_at = ?, finished_at = ? "
                    "WHERE run_id = ? AND tenant_id = ?",
                    (now, now, run_id, effective),
                )
            else:
                # Dev posture only — research/prod fails in _check_run_store_tenant_scope above.
                self._conn.execute(
                    "UPDATE run_records "
                    "SET status = 'cancelled', cancellation_flag = 1, updated_at = ?, finished_at = ? "
                    "WHERE run_id = ?",
                    (now, now, run_id),
                )
            self._conn.commit()

    def mark_complete(
        self, run_id: str, result_summary: str, workspace: str | None = None
    ) -> None:
        """Set status=completed and store result_summary.

        W34+ D.2 mirror: ``workspace`` is required under research/prod;
        dev back-compat allows None with a logged warning.

        Args:
            run_id: Identifier of the run.
            result_summary: Human-readable or serialized run result.
            workspace: Optional tenant workspace ID.  When provided, restricts
                the UPDATE to rows owned by the given tenant.
        """
        workspace = _check_run_store_tenant_scope(workspace, method="mark_complete")
        now = time.time()
        with self._lock:
            if workspace is not None:
                self._conn.execute(
                    "UPDATE run_records "
                    "SET status = 'completed', result_summary = ?, updated_at = ?, finished_at = ? "
                    "WHERE run_id = ? AND tenant_id = ?",
                    (result_summary, now, now, run_id, workspace),
                )
            else:
                # scope: process-internal — workspace scoping deferred, all callers must be audited
                self._conn.execute(
                    "UPDATE run_records "
                    "SET status = 'completed', result_summary = ?, updated_at = ?, finished_at = ? "
                    "WHERE run_id = ?",
                    (result_summary, now, now, run_id),
                )
            self._conn.commit()

    def mark_failed(
        self, run_id: str, error_summary: str, workspace: str | None = None
    ) -> None:
        """Set status=failed and store error_summary.

        W34+ D.2 mirror: ``workspace`` required under research/prod; dev warns.

        Args:
            run_id: Identifier of the run.
            error_summary: Error description.
            workspace: Optional tenant workspace ID.  When provided, restricts
                the UPDATE to rows owned by the given tenant.
        """
        workspace = _check_run_store_tenant_scope(workspace, method="mark_failed")
        now = time.time()
        with self._lock:
            if workspace is not None:
                self._conn.execute(
                    "UPDATE run_records "
                    "SET status = 'failed', error_summary = ?, updated_at = ?, finished_at = ? "
                    "WHERE run_id = ? AND tenant_id = ?",
                    (error_summary, now, now, run_id, workspace),
                )
            else:
                # scope: process-internal — workspace scoping deferred, all callers must be audited
                self._conn.execute(
                    "UPDATE run_records "
                    "SET status = 'failed', error_summary = ?, updated_at = ?, finished_at = ? "
                    "WHERE run_id = ?",
                    (error_summary, now, now, run_id),
                )
            self._conn.commit()

    def is_cancelled(self, run_id: str, workspace: str | None = None) -> bool:
        """Return True if the run's cancellation_flag is set.

        W34+ D.2 mirror: ``workspace`` required under research/prod; dev warns.

        Args:
            run_id: Identifier of the run.
            workspace: Optional tenant workspace ID.  When provided, restricts
                the query to rows owned by the given tenant.

        Returns:
            True if the run exists and cancellation_flag is True, else False.
        """
        workspace = _check_run_store_tenant_scope(workspace, method="is_cancelled")
        with self._lock:
            if workspace is not None:
                cur = self._conn.execute(
                    "SELECT cancellation_flag FROM run_records "
                    "WHERE run_id = ? AND tenant_id = ?",
                    (run_id, workspace),
                )
            else:
                # scope: process-internal — workspace scoping deferred, all callers must be audited
                cur = self._conn.execute(
                    "SELECT cancellation_flag FROM run_records WHERE run_id = ?",
                    (run_id,),
                )
            row = cur.fetchone()
        if row is None:
            return False
        return bool(row[0])

    def list_runs_by_project(self, tenant_id: str, project_id: str) -> list[RunRecord]:
        """Return all run records for a tenant scoped to a project.

        Args:
            tenant_id: Tenant whose runs to retrieve.
            project_id: Project scope to filter by.

        Returns:
            List of RunRecord instances ordered by created_at ascending.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                "status, priority, attempt_count, cancellation_flag, result_summary, "
                "error_summary, created_at, updated_at, project_id, finished_at, "
                "parent_run_id, attempt_id, phase_id "
                "FROM run_records WHERE tenant_id = ? AND project_id = ? "
                "ORDER BY created_at ASC",
                (tenant_id, project_id),
            )
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def mark_running(self, run_id: str, workspace: str | None = None) -> None:
        """Set status=running. Called when RunManager begins execution.

        W34+ D.2 mirror: ``workspace`` required under research/prod; dev warns.

        Args:
            run_id: Identifier of the run.
            workspace: Optional tenant workspace ID.  When provided, restricts
                the UPDATE to rows owned by the given tenant.
        """
        workspace = _check_run_store_tenant_scope(workspace, method="mark_running")
        now = time.time()
        with self._lock:
            if workspace is not None:
                self._conn.execute(
                    "UPDATE run_records SET status = 'running', updated_at = ? "
                    "WHERE run_id = ? AND tenant_id = ?",
                    (now, run_id, workspace),
                )
            else:
                # scope: process-internal — workspace scoping deferred, all callers must be audited
                self._conn.execute(
                    "UPDATE run_records SET status = 'running', updated_at = ? WHERE run_id = ?",
                    (now, run_id),
                )
            self._conn.commit()

    def delete(self, run_id: str, workspace: str | None = None) -> None:
        """Delete a run record. Used as rollback primitive when creation fails post-insert.

        W34+ D.2 mirror: ``workspace`` required under research/prod; dev warns.

        Args:
            run_id: Identifier of the run to delete.
            workspace: Optional tenant workspace ID.  When provided, restricts
                the DELETE to rows owned by the given tenant.
        """
        workspace = _check_run_store_tenant_scope(workspace, method="delete")
        with self._lock:
            if workspace is not None:
                self._conn.execute(
                    "DELETE FROM run_records WHERE run_id = ? AND tenant_id = ?",
                    (run_id, workspace),
                )
            else:
                # scope: process-internal — workspace scoping deferred, all callers must be audited
                self._conn.execute("DELETE FROM run_records WHERE run_id = ?", (run_id,))
            self._conn.commit()

    def list_pending(self) -> list[RunRecord]:
        """Return all runs in non-terminal status (queued or running).

        Used at startup to rehydrate runs that were in-flight when the
        process was killed.

        Returns:
            List of RunRecord instances with status 'queued' or 'running',
            ordered by created_at ascending.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, tenant_id, user_id, session_id, task_contract_json, "
                "status, priority, attempt_count, cancellation_flag, result_summary, "
                "error_summary, created_at, updated_at, project_id, finished_at, "
                "parent_run_id, attempt_id, phase_id "
                "FROM run_records WHERE status IN ('queued', 'running') "
                "ORDER BY created_at ASC",
            )
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
