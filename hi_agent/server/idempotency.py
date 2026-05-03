"""SQLite-backed idempotency store for deduplicating API requests.

Prevents duplicate run creation when clients retry requests with the same
idempotency key.  Uses WAL mode and a threading.Lock for thread safety.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext


@dataclass
class IdempotencyRecord:
    """Persisted state for a single idempotency key."""

    tenant_id: str
    idempotency_key: str
    request_hash: str  # SHA-256 of canonical sorted-key JSON payload
    run_id: str
    status: str  # "pending" | "completed" | "failed" | "cancelled" | "timed_out"
    response_snapshot: str  # JSON-serialized final result, empty until complete
    created_at: float
    updated_at: float
    expires_at: float
    # RO-2: spine fields for cross-record traceability
    project_id: str = ""
    user_id: str = ""
    session_id: str = ""
    # Track D C-7: HTTP status code captured at terminal state so the replay
    # path can return the original outcome (5xx for failed, 200 for success)
    # instead of always returning 200. Defaults to 200 for legacy rows that
    # were stored before this column existed (treated as "succeeded").
    status_code: int = 200


def _hash_payload(payload: dict[str, Any]) -> str:
    """Return SHA-256 hex digest of canonicalized JSON payload."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


class IdempotencyStore:
    """SQLite-backed idempotency store.

    Thread-safe via ``check_same_thread=False`` plus an explicit
    ``threading.Lock`` that serializes all writes.
    """

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS idempotency_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         TEXT    NOT NULL,
    idempotency_key   TEXT    NOT NULL,
    request_hash      TEXT    NOT NULL,
    run_id            TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'pending',
    response_snapshot TEXT    NOT NULL DEFAULT '',
    created_at        REAL    NOT NULL,
    updated_at        REAL    NOT NULL,
    expires_at        REAL    NOT NULL,
    project_id        TEXT    NOT NULL,
    user_id           TEXT    NOT NULL DEFAULT '',
    session_id        TEXT    NOT NULL DEFAULT '',
    status_code       INTEGER NOT NULL DEFAULT 200,
    UNIQUE (tenant_id, idempotency_key)
)
"""
    _CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_idempotency_tenant_key
ON idempotency_records (tenant_id, idempotency_key)
"""

    def __init__(
        self,
        db_path: str | Path = ".hi_agent/idempotency.db",
    ) -> None:
        """Open (or create) the idempotency database.

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
        """Add RO-2 spine columns to existing databases via ALTER TABLE."""
        cx = self._conn
        cols = {row[1] for row in cx.execute("PRAGMA table_info(idempotency_records)")}
        if "project_id" not in cols:
            cx.execute(
                "ALTER TABLE idempotency_records ADD COLUMN project_id TEXT NOT NULL DEFAULT ''"  # migration compat: legacy rows get empty string  # noqa: E501  # expiry_wave: permanent
            )
        if "user_id" not in cols:
            cx.execute(
                "ALTER TABLE idempotency_records ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"
            )
        if "session_id" not in cols:
            cx.execute(
                "ALTER TABLE idempotency_records ADD COLUMN session_id TEXT NOT NULL DEFAULT ''"
            )
        # Track D C-7: status_code column for replay HTTP-status fidelity.
        if "status_code" not in cols:
            cx.execute(
                "ALTER TABLE idempotency_records "
                "ADD COLUMN status_code INTEGER NOT NULL DEFAULT 200"
            )
        cx.commit()

    def _row_to_record(self, row: tuple) -> IdempotencyRecord:
        # row carries 12 spine fields plus an optional status_code at index 12
        # (legacy SELECTs that omit it pass len 12 — default to 200).
        status_code = int(row[12]) if len(row) > 12 and row[12] is not None else 200
        return IdempotencyRecord(
            tenant_id=row[0],
            idempotency_key=row[1],
            request_hash=row[2],
            run_id=row[3],
            status=row[4],
            response_snapshot=row[5],
            created_at=row[6],
            updated_at=row[7],
            expires_at=row[8],
            project_id=row[9],
            user_id=row[10],
            session_id=row[11],
            status_code=status_code,
        )

    # -- public API ----------------------------------------------------------

    def reserve_or_replay(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_hash: str,
        run_id: str,
        ttl_seconds: float = 86400.0,
        project_id: str = "",
        user_id: str = "",
        session_id: str = "",
        exec_ctx: RunExecutionContext | None = None,
    ) -> tuple[Literal["created", "replayed", "conflict"], IdempotencyRecord]:
        """Reserve a new idempotency slot or replay/conflict an existing one.

        RO-9: Uses INSERT + catch-on-IntegrityError for atomic reserve under
        concurrent submissions. SQLite serializes writers, so the UNIQUE
        constraint guarantees exactly one winner.

        Args:
            tenant_id: Authenticated tenant (from TenantContext, not request body).
            idempotency_key: Client-supplied idempotency key.
            request_hash: SHA-256 of the canonical request payload.
            run_id: The run_id to associate on first creation.
            ttl_seconds: How long (seconds) before the record expires.
            project_id: Project scope from the run contract (RO-2).
            user_id: Authenticated user (from TenantContext) (RO-2).
            session_id: Session scope from TenantContext (RO-2).
            exec_ctx: Optional RunExecutionContext; when provided, spine fields
                (tenant_id, user_id, session_id, project_id) are sourced from
                it, overriding the positional arguments for those fields.

        Returns:
            A tuple of (outcome, record) where outcome is one of:
            - ``"created"``  — first time this key is seen; record inserted.
            - ``"replayed"`` — same key AND same hash; existing record returned.
            - ``"conflict"`` — same key but DIFFERENT hash; existing record
              returned (caller should raise 409).
        """
        if exec_ctx is not None:
            if exec_ctx.tenant_id:
                tenant_id = exec_ctx.tenant_id
            if exec_ctx.user_id:
                user_id = exec_ctx.user_id
            if exec_ctx.session_id:
                session_id = exec_ctx.session_id
            if exec_ctx.project_id:
                project_id = exec_ctx.project_id
        now = time.time()
        expires_at = now + ttl_seconds

        with self._lock:
            # RO-9: attempt atomic INSERT; on UNIQUE violation read the winner back.
            try:
                self._conn.execute(
                    "INSERT INTO idempotency_records "
                    "(tenant_id, idempotency_key, request_hash, run_id, status, "
                    "response_snapshot, created_at, updated_at, expires_at, "
                    "project_id, user_id, session_id) "
                    "VALUES (?, ?, ?, ?, 'pending', '', ?, ?, ?, ?, ?, ?)",
                    (
                        tenant_id,
                        idempotency_key,
                        request_hash,
                        run_id,
                        now,
                        now,
                        expires_at,
                        project_id,
                        user_id,
                        session_id,
                    ),
                )
                self._conn.commit()
                record = IdempotencyRecord(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    run_id=run_id,
                    status="pending",
                    response_snapshot="",
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                    project_id=project_id,
                    user_id=user_id,
                    session_id=session_id,
                )
                return "created", record
            except sqlite3.IntegrityError:
                # UNIQUE violation: another concurrent insert won the race.
                # Fall through to read the existing record.
                self._conn.rollback()

            cur = self._conn.execute(
                "SELECT tenant_id, idempotency_key, request_hash, run_id, "
                "status, response_snapshot, created_at, updated_at, expires_at, "
                "project_id, user_id, session_id, status_code "
                "FROM idempotency_records "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (tenant_id, idempotency_key),
            )
            row = cur.fetchone()
            if row is None:
                # Should not happen after IntegrityError, but guard defensively.
                raise RuntimeError(
                    f"idempotency record vanished after UNIQUE conflict for key={idempotency_key!r}"
                )
            record = self._row_to_record(row)
            outcome: Literal["created", "replayed", "conflict"] = (
                "replayed" if record.request_hash == request_hash else "conflict"
            )
            return outcome, record

    # HD-7: identity / observability fields stripped from the snapshot prior
    # to persistence so that an idempotency replay does not re-issue the
    # original ``request_id`` / ``trace_id`` / response timestamp on a new
    # request. The replayed body should describe *the work*, not the
    # original invocation envelope.
    _IDENTITY_FIELDS_STRIPPED_ON_REPLAY: tuple[str, ...] = (
        "request_id",
        "trace_id",
        "x_request_id",
        "_response_timestamp",
    )

    @classmethod
    def _normalize_response_for_replay(cls, response_json: str) -> str:
        """Strip per-call identity metadata from a JSON response snapshot.

        HD-7: ``request_id`` / ``trace_id`` / ``x_request_id`` /
        ``_response_timestamp`` are observability surfaces tied to the
        original request — replaying them would falsify trace lineage on
        the second caller. We drop them here so the stored snapshot is
        a *pure result*; consumers re-decorate at the route layer with
        fresh values for the replaying request.

        Returns the input unchanged if it is empty, not a JSON object, or
        contains no stripped fields.
        """
        if not response_json:
            return response_json
        try:
            payload = json.loads(response_json)
        except (ValueError, json.JSONDecodeError):
            return response_json  # not JSON — leave alone
        if not isinstance(payload, dict):
            return response_json
        stripped = False
        for field in cls._IDENTITY_FIELDS_STRIPPED_ON_REPLAY:
            if field in payload:
                payload.pop(field, None)
                stripped = True
        if not stripped:
            return response_json
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    # Track D C-7: default HTTP status codes per terminal_state. Callers can
    # override via the ``status_code`` kwarg when the upstream layer knows
    # the exact code that was originally returned (e.g. 409 for conflict).
    _DEFAULT_STATUS_CODE_BY_TERMINAL: ClassVar[dict[str, int]] = {
        "succeeded": 200,
        "failed": 500,
        "cancelled": 499,  # client-cancelled — same convention as nginx 499
        "timed_out": 504,
    }

    @classmethod
    def default_status_code_for(cls, terminal_state: str) -> int:
        """Return the default HTTP status code for a terminal_state."""
        return cls._DEFAULT_STATUS_CODE_BY_TERMINAL.get(terminal_state, 500)

    def mark_complete(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_json: str,
        terminal_state: str = "succeeded",
        *,
        status_code: int | None = None,
    ) -> None:
        """Mark an idempotency record as complete with a terminal state snapshot.

        RO-7: the stored status reflects the actual run outcome so that replays
        can surface the precise terminal state to callers.

        HD-7: per-call identity fields (``request_id``, ``trace_id``,
        ``x_request_id``, ``_response_timestamp``) are stripped from
        ``response_json`` before storage so a replay does not re-emit the
        original request's trace metadata.

        Track D C-7: ``status_code`` records the original HTTP status code so
        a replay returns the same code (e.g. 500 for a failed run, 200 for a
        completed run). When omitted, a default is inferred from
        ``terminal_state`` via :meth:`default_status_code_for`.

        Args:
            tenant_id: Tenant owning the record.
            idempotency_key: Client-supplied idempotency key.
            response_json: JSON-serialized final result.
            terminal_state: One of "succeeded", "failed", "cancelled",
                "timed_out". Stored verbatim as the record status.
            status_code: HTTP status code that was originally returned for
                this run. When None, defaulted from ``terminal_state``.
        """
        _valid = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
        status = terminal_state if terminal_state in _valid else "succeeded"
        resolved_code = (
            int(status_code)
            if status_code is not None
            else self.default_status_code_for(status)
        )
        normalized_response = self._normalize_response_for_replay(response_json)
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE idempotency_records "
                "SET status = ?, response_snapshot = ?, updated_at = ?, status_code = ? "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (status, normalized_response, now, resolved_code, tenant_id, idempotency_key),
            )
            self._conn.commit()

    def mark_failed(
        self,
        tenant_id: str,
        idempotency_key: str,
        *,
        status_code: int = 500,
    ) -> None:
        """Mark an idempotency record as failed.

        Track D C-7: persists ``status_code`` (default 500) so a replay
        surfaces the original failure rather than masquerading as 200.

        Args:
            tenant_id: Tenant owning the record.
            idempotency_key: Client-supplied idempotency key.
            status_code: HTTP status code that was originally returned;
                defaulted to 500 when the failure happened before a code
                was determined.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE idempotency_records "
                "SET status = 'failed', updated_at = ?, status_code = ? "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (now, int(status_code), tenant_id, idempotency_key),
            )
            self._conn.commit()

    def release(self, tenant_id: str, idempotency_key: str) -> None:
        """Delete a pending idempotency slot. Rollback primitive for create_run failures.

        Only deletes records in status='pending'. Completed/failed records are not removed
        (they are needed for replay).

        Args:
            tenant_id: Tenant owning the record.
            idempotency_key: Client-supplied idempotency key.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM idempotency_records "
                "WHERE tenant_id = ? AND idempotency_key = ? AND status = 'pending'",
                (tenant_id, idempotency_key),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
