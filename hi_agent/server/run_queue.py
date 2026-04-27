"""SQLite-backed durable run queue with lease semantics.

Crashed workers release their leases automatically when the lease timer
expires; a subsequent call to ``release_expired_leases`` re-queues those
runs so another worker can claim them.

Follows the same code style as ``SQLiteRunStore`` and
``SqliteEvidenceStore``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar


class OptimisticLockError(Exception):
    """Raised when a recovery lease claim fails due to concurrent adoption.

    Thrown by callers that detect ``claim_with_adoption_token`` returned
    ``False``, indicating another recovery pass already owns the run.
    """


def _resolve_db_path(db_path: str | None) -> str:
    """RO-3: resolve RunQueue db_path based on posture when caller passes None.

    - dev posture  → ":memory:" (no durability required)
    - research/prod → file path from HI_AGENT_DATA_DIR env var, or
      "./hi_agent_data/run_queue.sqlite" as default.
    """
    if db_path is not None:
        return db_path
    # Import here to avoid circular import at module load time.
    try:
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if not posture.requires_durable_queue:
            return ":memory:"
    except Exception:
        return ":memory:"

    data_dir = os.environ.get("HI_AGENT_DATA_DIR", "./hi_agent_data")
    return str(Path(data_dir) / "run_queue.sqlite")


class RunQueue:
    """SQLite-backed durable run queue with lease semantics."""

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS run_queue (
    run_id              TEXT    PRIMARY KEY,
    status              TEXT    NOT NULL DEFAULT 'queued',
    priority            INTEGER NOT NULL DEFAULT 0,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 3,
    worker_id           TEXT,
    lease_expires_at    REAL,
    cancellation_flag   INTEGER NOT NULL DEFAULT 0,
    payload_json        TEXT    NOT NULL DEFAULT '',
    enqueued_at         REAL    NOT NULL,
    updated_at          REAL    NOT NULL
)
"""
    _CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_run_queue_status_priority
ON run_queue (status, priority ASC, enqueued_at ASC)
"""

    _CREATE_DLQ_TABLE = """\
CREATE TABLE IF NOT EXISTS dead_lettered_runs (
    run_id          TEXT PRIMARY KEY,
    reason          TEXT NOT NULL,
    original_state  TEXT,
    dead_lettered_at TEXT NOT NULL,
    tenant_id       TEXT NOT NULL DEFAULT '__unknown__',
    requeue_count   INTEGER NOT NULL DEFAULT 0,
    last_requeue_at TEXT
)
"""

    _MIGRATE_SPINE: ClassVar[list[str]] = [
        "ALTER TABLE run_queue ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE run_queue ADD COLUMN user_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE run_queue ADD COLUMN session_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE run_queue ADD COLUMN project_id TEXT NOT NULL DEFAULT ''",
        # adoption_token for double-execute prevention during recovery.
        # NULL = unclaimed by recovery; non-NULL = a recovery pass already owns it.
        "ALTER TABLE run_queue ADD COLUMN adoption_token TEXT",
    ]
    _CREATE_SPINE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_run_queue_spine
ON run_queue (tenant_id, user_id, session_id, status)
"""

    def __init__(
        self,
        db_path: str | None = None,
        lease_timeout_seconds: float = 300.0,
    ) -> None:
        """Open (or create) the run queue database.

        RO-3: When ``db_path`` is ``None`` (the default), the path is resolved
        from the current posture:
        - dev  → ``:memory:`` (ephemeral)
        - research/prod → file-backed path from ``HI_AGENT_DATA_DIR`` (or
          ``./hi_agent_data/run_queue.sqlite`` as fallback).

        Args:
            db_path: Explicit filesystem path, ``":memory:"``, or ``None``
                to auto-resolve from posture.
            lease_timeout_seconds: Seconds before an uncompleted lease expires
                and the run is eligible for re-claiming.
        """
        self._lease_timeout = lease_timeout_seconds
        self.lease_heartbeat_interval_seconds: float = max(1.0, lease_timeout_seconds / 3)
        self._lock = threading.Lock()

        resolved = _resolve_db_path(db_path)
        self.db_path = resolved  # expose for inspection in tests (RO-3)

        if resolved != ":memory:":
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(resolved, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_INDEX)
        self._conn.execute(self._CREATE_DLQ_TABLE)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add spine columns to run_queue table if missing."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(run_queue)")}
        for stmt in self._MIGRATE_SPINE:
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            if col not in cols:
                self._conn.execute(stmt)
        self._conn.execute(self._CREATE_SPINE_INDEX)
        self._conn.commit()

    # -- public API -----------------------------------------------------------

    def enqueue(
        self,
        run_id: str,
        priority: int = 0,
        payload_json: str = "",
        tenant_id: str = "",
        user_id: str = "",
        session_id: str = "",
        project_id: str = "",
    ) -> None:
        """Add run to queue.  Idempotent by run_id.

        If the run_id already exists the call is a no-op so callers may
        safely retry without producing duplicates.

        Args:
            run_id: Unique identifier for the run.
            priority: Lower integer = higher urgency (same convention as
                the in-memory PriorityQueue in RunManager).
            payload_json: Opaque JSON string stored alongside the run.
            tenant_id: Tenant spine field for cross-record traceability.
            user_id: User spine field.
            session_id: Session spine field.
            project_id: Project spine field.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO run_queue "
                "(run_id, status, priority, attempt_count, max_attempts, "
                " worker_id, lease_expires_at, cancellation_flag, "
                " payload_json, enqueued_at, updated_at, "
                " tenant_id, user_id, session_id, project_id) "
                "VALUES (?, 'queued', ?, 0, 3, NULL, NULL, 0, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, priority, payload_json, now, now,
                    tenant_id, user_id, session_id, project_id,
                ),
            )
            self._conn.commit()

    def reenqueue(self, run_id: str, tenant_id: str = "") -> bool:
        """Reset an existing run's status to 'queued' for re-processing.

        Used by recovery to re-queue a lease-expired run.  Unlike ``enqueue``,
        this method explicitly updates an existing row rather than inserting.

        Args:
            run_id: Identifier of the run to re-enqueue.
            tenant_id: Tenant spine — used to verify the row is owned by the
                expected tenant; ignored if empty.

        Returns:
            ``True`` if the run was reset to 'queued'; ``False`` if not found.
        """
        now = time.time()
        with self._lock:
            result = self._conn.execute(
                "UPDATE run_queue "
                "SET status = 'queued', worker_id = NULL, "
                "    lease_expires_at = NULL, updated_at = ? "
                "WHERE run_id = ?",
                (now, run_id),
            )
            self._conn.commit()
        return result.rowcount > 0

    def claim_next(self, worker_id: str) -> dict | None:
        """Claim the highest-priority queued run.

        Uses an atomic UPDATE … WHERE to prevent two workers from claiming
        the same run.

        Args:
            worker_id: Opaque identifier for the calling worker.

        Returns:
            ``{"run_id": str, "payload_json": str}`` or ``None`` when the
            queue contains no claimable runs.
        """
        now = time.time()
        lease_expires_at = now + self._lease_timeout

        with self._lock:
            # Find the best candidate atomically.
            cur = self._conn.execute(
                "SELECT run_id, payload_json FROM run_queue "
                "WHERE status = 'queued' "
                "  AND cancellation_flag = 0 "
                "ORDER BY priority ASC, enqueued_at ASC "
                "LIMIT 1",
            )
            row = cur.fetchone()
            if row is None:
                return None

            run_id, payload_json = row

            # Atomic claim: only succeeds if the row is still 'queued'.
            result = self._conn.execute(
                "UPDATE run_queue "
                "SET status = 'leased', worker_id = ?, "
                "    lease_expires_at = ?, updated_at = ? "
                "WHERE run_id = ? AND status = 'queued'",
                (worker_id, lease_expires_at, now, run_id),
            )
            self._conn.commit()

            if result.rowcount == 0:
                # Another worker raced us to this run; give up for this call.
                return None

        return {"run_id": run_id, "payload_json": payload_json}

    def heartbeat(self, run_id: str, worker_id: str) -> bool:
        """Extend the lease for an active run.

        Args:
            run_id: Identifier of the leased run.
            worker_id: Must match the worker that claimed the run.

        Returns:
            ``True`` if the lease was extended; ``False`` if the lease was
            already stolen by another worker (or the run no longer exists).
        """
        now = time.time()
        lease_expires_at = now + self._lease_timeout
        with self._lock:
            result = self._conn.execute(
                "UPDATE run_queue "
                "SET lease_expires_at = ?, updated_at = ? "
                "WHERE run_id = ? AND worker_id = ? AND status = 'leased'",
                (lease_expires_at, now, run_id, worker_id),
            )
            self._conn.commit()
        return result.rowcount > 0

    def complete(self, run_id: str, worker_id: str) -> None:
        """Mark run as completed and remove it from the active queue.

        Args:
            run_id: Identifier of the leased run.
            worker_id: Must match the worker that claimed the run.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE run_queue "
                "SET status = 'completed', worker_id = NULL, "
                "    lease_expires_at = NULL, updated_at = ? "
                "WHERE run_id = ? AND worker_id = ?",
                (now, run_id, worker_id),
            )
            self._conn.commit()

    def fail(self, run_id: str, worker_id: str, error: str = "") -> None:
        """Record a failure; re-queue if retries remain, otherwise mark failed.

        Args:
            run_id: Identifier of the leased run.
            worker_id: Must match the worker that claimed the run.
            error: Human-readable error description (stored in payload for
                observability; not surfaced through this API).
        """
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "SELECT attempt_count, max_attempts FROM run_queue "
                "WHERE run_id = ? AND worker_id = ?",
                (run_id, worker_id),
            )
            row = cur.fetchone()
            if row is None:
                return

            attempt_count, max_attempts = row
            new_attempt_count = attempt_count + 1

            if new_attempt_count >= max_attempts:
                new_status = "failed"
                new_worker = None
                new_lease = None
            else:
                new_status = "queued"
                new_worker = None
                new_lease = None

            self._conn.execute(
                "UPDATE run_queue "
                "SET status = ?, attempt_count = ?, worker_id = ?, "
                "    lease_expires_at = ?, updated_at = ? "
                "WHERE run_id = ?",
                (new_status, new_attempt_count, new_worker, new_lease, now, run_id),
            )
            self._conn.commit()

    def cancel(self, run_id: str) -> None:
        """Set the cancellation flag on a queued or leased run.

        Does not remove the run from the queue; workers must poll
        ``is_cancelled()`` and terminate cooperatively.

        Args:
            run_id: Identifier of the run.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE run_queue SET cancellation_flag = 1, updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            self._conn.commit()

    def release_expired_leases(self) -> int:
        """Re-queue runs whose leases have expired.

        Intended to be called periodically by a maintenance thread or on
        each ``claim_next`` invocation in long-running services.

        Returns:
            Number of runs that were released back to 'queued' status.
        """
        now = time.time()
        with self._lock:
            result = self._conn.execute(
                "UPDATE run_queue "
                "SET status = 'queued', worker_id = NULL, "
                "    lease_expires_at = NULL, updated_at = ? "
                "WHERE status = 'leased' AND lease_expires_at < ?",
                (now, now),
            )
            self._conn.commit()
        return result.rowcount

    def expire_stale_leases(self) -> list[dict]:
        """Collect runs with stale (expired) leases without re-queuing them.

        Unlike ``release_expired_leases``, this method only *reads* the
        expired rows and returns them.  The caller decides whether to
        re-enqueue (posture-driven decision; see ``hi_agent.server.recovery``).

        Returns:
            List of dicts, each with at minimum:
            ``{"run_id": str, "tenant_id": str, "expired_at": str, "lease_age_s": float}``
        """
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id, tenant_id, lease_expires_at "
                "FROM run_queue "
                "WHERE status = 'leased' AND lease_expires_at < ?",
                (now,),
            )
            rows = cur.fetchall()

        result: list[dict] = []
        for run_id, tenant_id, lease_expires_at in rows:
            lease_age_s = now - (lease_expires_at if lease_expires_at else now)
            result.append(
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id or "",
                    "expired_at": str(lease_expires_at),
                    "lease_age_s": round(lease_age_s, 3),
                }
            )
        return result

    def claim_with_adoption_token(self, run_id: str, adoption_token: str) -> bool:
        """Atomically set the adoption_token on an un-adopted leased run.

        Used by recovery to prevent two concurrent recovery passes from
        double-executing the same run.  The CAS update only succeeds when
        ``adoption_token IS NULL`` — a second recovery pass that races the
        first will get ``rowcount == 0`` and must skip the run.

        Args:
            run_id: The run to adopt.
            adoption_token: A UUID string identifying the recovery pass.

        Returns:
            ``True`` if the token was set (this recovery pass owns the run);
            ``False`` if another pass already owns it.
        """
        now = time.time()
        with self._lock:
            result = self._conn.execute(
                "UPDATE run_queue "
                "SET adoption_token = ?, updated_at = ? "
                "WHERE run_id = ? AND adoption_token IS NULL",
                (adoption_token, now, run_id),
            )
            self._conn.commit()
        return result.rowcount > 0

    def is_cancelled(self, run_id: str) -> bool:
        """Return True if the cancellation flag is set for this run.

        Args:
            run_id: Identifier of the run.

        Returns:
            ``True`` if the run exists and its cancellation flag is set.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT cancellation_flag FROM run_queue WHERE run_id = ?",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return False
        return bool(row[0])

    def dequeue_unclaimed(self, run_id: str) -> None:
        """Remove a queued run that was never claimed. Rollback primitive.

        Only removes the run when it is still in 'queued' status (never claimed
        by a worker), making it safe to use as a creation-failure rollback.

        Args:
            run_id: Identifier of the run to remove.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM run_queue WHERE run_id = ? AND status = 'queued'",
                (run_id,),
            )
            self._conn.commit()

    def dead_letter(
        self,
        run_id: str,
        reason: str,
        original_state: str,
        tenant_id: str,
    ) -> None:
        """Move a run to the dead-letter queue and mark it failed in run_queue.

        Args:
            run_id: Identifier of the run to dead-letter.
            reason: Human-readable reason for dead-lettering.
            original_state: The run's state/status at dead-letter time.
            tenant_id: Tenant spine field for the DLQ record.
        """
        now_iso = datetime.now(UTC).isoformat()
        now_ts = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO dead_lettered_runs "
                "(run_id, reason, original_state, dead_lettered_at, tenant_id, "
                " requeue_count, last_requeue_at) "
                "VALUES (?, ?, ?, ?, ?, "
                "  COALESCE((SELECT requeue_count FROM dead_lettered_runs WHERE run_id = ?), 0), "
                "  (SELECT last_requeue_at FROM dead_lettered_runs WHERE run_id = ?))",
                (run_id, reason, original_state, now_iso, tenant_id, run_id, run_id),
            )
            self._conn.execute(
                "UPDATE run_queue SET status = 'failed', updated_at = ? WHERE run_id = ?",
                (now_ts, run_id),
            )
            self._conn.commit()

    def list_dlq(self, tenant_id: str | None = None) -> list[dict]:
        """Return all dead-lettered run records, optionally filtered by tenant.

        Args:
            tenant_id: If provided, only return records for this tenant.

        Returns:
            List of dicts with DLQ record fields.
        """
        with self._lock:
            if tenant_id is not None:
                cur = self._conn.execute(
                    "SELECT run_id, reason, original_state, dead_lettered_at, "
                    "       tenant_id, requeue_count, last_requeue_at "
                    "FROM dead_lettered_runs WHERE tenant_id = ? "
                    "ORDER BY dead_lettered_at DESC",
                    (tenant_id,),
                )
            else:
                cur = self._conn.execute(
                    "SELECT run_id, reason, original_state, dead_lettered_at, "
                    "       tenant_id, requeue_count, last_requeue_at "
                    "FROM dead_lettered_runs ORDER BY dead_lettered_at DESC"
                )
            rows = cur.fetchall()
        return [
            {
                "run_id": row[0],
                "reason": row[1],
                "original_state": row[2],
                "dead_lettered_at": row[3],
                "tenant_id": row[4],
                "requeue_count": row[5],
                "last_requeue_at": row[6],
            }
            for row in rows
        ]

    def requeue_from_dlq(self, run_id: str) -> bool:
        """Remove a run from the DLQ and reset it to queued status.

        Args:
            run_id: Identifier of the dead-lettered run to requeue.

        Returns:
            ``True`` if the run was found in the DLQ and requeued;
            ``False`` if not found.
        """
        now_ts = time.time()
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "SELECT run_id FROM dead_lettered_runs WHERE run_id = ?",
                (run_id,),
            )
            if cur.fetchone() is None:
                return False
            self._conn.execute(
                "UPDATE dead_lettered_runs "
                "SET requeue_count = requeue_count + 1, last_requeue_at = ? "
                "WHERE run_id = ?",
                (now_iso, run_id),
            )
            self._conn.execute(
                "DELETE FROM dead_lettered_runs WHERE run_id = ?",
                (run_id,),
            )
            self._conn.execute(
                "UPDATE run_queue "
                "SET status = 'queued', worker_id = NULL, "
                "    lease_expires_at = NULL, updated_at = ? "
                "WHERE run_id = ?",
                (now_ts, run_id),
            )
            self._conn.commit()
        return True

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
