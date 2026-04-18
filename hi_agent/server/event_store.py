"""SQLite-backed durable event store for per-run event persistence and replay."""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field


@dataclass
class StoredEvent:
    """One persisted runtime event row."""

    event_id: str
    run_id: str
    sequence: int          # = RuntimeEvent.commit_offset
    event_type: str
    payload_json: str      # serialized full event (JSON string)
    tenant_id: str = ""
    trace_id: str = ""
    created_at: float = field(default_factory=time.time)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT    NOT NULL UNIQUE,
    run_id      TEXT    NOT NULL,
    sequence    INTEGER NOT NULL,
    event_type  TEXT    NOT NULL,
    payload_json TEXT   NOT NULL DEFAULT '',
    tenant_id   TEXT    NOT NULL DEFAULT '',
    trace_id    TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events (run_id, sequence);
"""


class SQLiteEventStore:
    """Durable event store backed by SQLite.

    Events written here before publishing to the in-memory bus so that
    SSE clients that reconnect with a ``Last-Event-ID`` header can receive
    missed events from this store.

    Thread safety: a single ``threading.Lock`` serialises all writes;
    reads use a separate connection opened per ``list_since`` call so they
    never block concurrent writers for long.

    WAL mode is enabled so readers never block writers.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: StoredEvent) -> None:
        """Persist *event*.  Idempotent: duplicate ``event_id`` is silently ignored."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO run_events
                    (event_id, run_id, sequence, event_type, payload_json,
                     tenant_id, trace_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.sequence,
                    event.event_type,
                    event.payload_json,
                    event.tenant_id,
                    event.trace_id,
                    event.created_at,
                ),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_since(self, run_id: str, since_sequence: int = 0) -> list[StoredEvent]:
        """Return events for *run_id* with sequence > *since_sequence*, ordered by sequence."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT event_id, run_id, sequence, event_type, payload_json,
                       tenant_id, trace_id, created_at
                FROM   run_events
                WHERE  run_id = ? AND sequence > ?
                ORDER  BY sequence ASC
                """,
                (run_id, since_sequence),
            )
            rows = cursor.fetchall()
        return [
            StoredEvent(
                event_id=row[0],
                run_id=row[1],
                sequence=row[2],
                event_type=row[3],
                payload_json=row[4],
                tenant_id=row[5],
                trace_id=row[6],
                created_at=row[7],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()
