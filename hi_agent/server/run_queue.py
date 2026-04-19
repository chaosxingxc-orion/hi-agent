"""SQLite-backed durable run queue with lease semantics.

Crashed workers release their leases automatically when the lease timer
expires; a subsequent call to ``release_expired_leases`` re-queues those
runs so another worker can claim them.

Follows the same code style as ``SQLiteRunStore`` and
``SqliteEvidenceStore``.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


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

    def __init__(
        self,
        db_path: str = ":memory:",
        lease_timeout_seconds: float = 300.0,
    ) -> None:
        """Open (or create) the run queue database.

        Args:
            db_path: Filesystem path or ``":memory:"`` for an in-memory DB.
            lease_timeout_seconds: Seconds before an uncompleted lease expires
                and the run is eligible for re-claiming.
        """
        self._lease_timeout = lease_timeout_seconds
        self._lock = threading.Lock()

        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_INDEX)
        self._conn.commit()

    # -- public API -----------------------------------------------------------

    def enqueue(
        self,
        run_id: str,
        priority: int = 0,
        payload_json: str = "",
    ) -> None:
        """Add run to queue.  Idempotent by run_id.

        If the run_id already exists the call is a no-op so callers may
        safely retry without producing duplicates.

        Args:
            run_id: Unique identifier for the run.
            priority: Lower integer = higher urgency (same convention as
                the in-memory PriorityQueue in RunManager).
            payload_json: Opaque JSON string stored alongside the run.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO run_queue "
                "(run_id, status, priority, attempt_count, max_attempts, "
                " worker_id, lease_expires_at, cancellation_flag, "
                " payload_json, enqueued_at, updated_at) "
                "VALUES (?, 'queued', ?, 0, 3, NULL, NULL, 0, ?, ?, ?)",
                (run_id, priority, payload_json, now, now),
            )
            self._conn.commit()

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
                "UPDATE run_queue "
                "SET cancellation_flag = 1, updated_at = ? "
                "WHERE run_id = ?",
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

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
