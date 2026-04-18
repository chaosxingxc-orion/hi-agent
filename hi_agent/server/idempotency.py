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
from typing import Any, Literal


@dataclass
class IdempotencyRecord:
    """Persisted state for a single idempotency key."""

    tenant_id: str
    idempotency_key: str
    request_hash: str          # SHA-256 of canonical sorted-key JSON payload
    run_id: str
    status: str                # "pending" | "completed" | "failed"
    response_snapshot: str     # JSON-serialized final result, empty until complete
    created_at: float
    updated_at: float
    expires_at: float


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
            str(self._db_path), check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_INDEX)
        self._conn.commit()

    # -- helpers -------------------------------------------------------------

    def _row_to_record(self, row: tuple) -> IdempotencyRecord:
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
        )

    # -- public API ----------------------------------------------------------

    def reserve_or_replay(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_hash: str,
        run_id: str,
        ttl_seconds: float = 86400.0,
    ) -> tuple[Literal["created", "replayed", "conflict"], IdempotencyRecord]:
        """Reserve a new idempotency slot or replay/conflict an existing one.

        Args:
            tenant_id: Tenant owning the request.
            idempotency_key: Client-supplied idempotency key.
            request_hash: SHA-256 of the canonical request payload.
            run_id: The run_id to associate on first creation.
            ttl_seconds: How long (seconds) before the record expires.

        Returns:
            A tuple of (outcome, record) where outcome is one of:
            - ``"created"``  — first time this key is seen; record inserted.
            - ``"replayed"`` — same key AND same hash; existing record returned.
            - ``"conflict"`` — same key but DIFFERENT hash; existing record
              returned (caller should raise 409).
        """
        now = time.time()
        expires_at = now + ttl_seconds

        with self._lock:
            # Try to fetch existing record first.
            cur = self._conn.execute(
                "SELECT tenant_id, idempotency_key, request_hash, run_id, "
                "status, response_snapshot, created_at, updated_at, expires_at "
                "FROM idempotency_records "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (tenant_id, idempotency_key),
            )
            row = cur.fetchone()

            if row is not None:
                record = self._row_to_record(row)
                outcome: Literal["created", "replayed", "conflict"] = (
                    "replayed" if record.request_hash == request_hash else "conflict"
                )
                return outcome, record

            # First time — insert.
            self._conn.execute(
                "INSERT INTO idempotency_records "
                "(tenant_id, idempotency_key, request_hash, run_id, status, "
                "response_snapshot, created_at, updated_at, expires_at) "
                "VALUES (?, ?, ?, ?, 'pending', '', ?, ?, ?)",
                (tenant_id, idempotency_key, request_hash, run_id, now, now, expires_at),
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
            )
            return "created", record

    def mark_complete(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_json: str,
    ) -> None:
        """Mark an idempotency record as completed with a response snapshot.

        Args:
            tenant_id: Tenant owning the record.
            idempotency_key: Client-supplied idempotency key.
            response_json: JSON-serialized final result.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE idempotency_records "
                "SET status = 'completed', response_snapshot = ?, updated_at = ? "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (response_json, now, tenant_id, idempotency_key),
            )
            self._conn.commit()

    def mark_failed(self, tenant_id: str, idempotency_key: str) -> None:
        """Mark an idempotency record as failed.

        Args:
            tenant_id: Tenant owning the record.
            idempotency_key: Client-supplied idempotency key.
        """
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE idempotency_records "
                "SET status = 'failed', updated_at = ? "
                "WHERE tenant_id = ? AND idempotency_key = ?",
                (now, tenant_id, idempotency_key),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
