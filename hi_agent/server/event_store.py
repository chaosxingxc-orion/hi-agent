"""SQLite-backed durable event store for per-run event persistence and replay."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hi_agent.observability.trace_context import TraceContextManager as _TraceCtxMgr

_TRACE_MGR = _TraceCtxMgr()

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext


@dataclass
class StoredEvent:
    """One persisted runtime event row."""

    event_id: str
    run_id: str
    sequence: int  # = RuntimeEvent.commit_offset
    event_type: str
    payload_json: str  # serialized full event (JSON string)
    tenant_id: str = ""
    user_id: str = "__legacy__"  # workspace owner; "__legacy__" for pre-migration rows
    session_id: str = "__legacy__"  # workspace session; "__legacy__" for pre-migration rows
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
    user_id     TEXT    NOT NULL DEFAULT '__legacy__',
    session_id  TEXT    NOT NULL DEFAULT '__legacy__',
    trace_id    TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events (run_id, sequence);
"""

_MIGRATE_RUN_EVENTS = """\
ALTER TABLE run_events ADD COLUMN user_id TEXT NOT NULL DEFAULT '__legacy__';
ALTER TABLE run_events ADD COLUMN session_id TEXT NOT NULL DEFAULT '__legacy__';
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
        self._migrate()

    def _migrate(self) -> None:
        cx = self._conn
        cols = {row[1] for row in cx.execute("PRAGMA table_info(run_events)")}
        if "user_id" not in cols:
            cx.execute(
                "ALTER TABLE run_events ADD COLUMN user_id TEXT NOT NULL DEFAULT '__legacy__'"
            )
        if "session_id" not in cols:
            cx.execute(
                "ALTER TABLE run_events ADD COLUMN session_id TEXT NOT NULL DEFAULT '__legacy__'"
            )
        cx.commit()
        cx.execute(
            "CREATE INDEX IF NOT EXISTS idx_run_events_workspace_run_seq "
            "ON run_events (tenant_id, user_id, session_id, run_id, sequence)"
        )
        cx.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: StoredEvent, *, exec_ctx: RunExecutionContext | None = None) -> None:
        """Persist *event*.  Idempotent: duplicate ``event_id`` is silently ignored.

        Args:
            event: The StoredEvent to persist.
            exec_ctx: Optional RunExecutionContext; when provided, spine fields
                (tenant_id, user_id, session_id, run_id) are derived from
                exec_ctx when the event's own fields are empty or legacy values.
        """
        if exec_ctx is not None:
            if exec_ctx.tenant_id:
                event.tenant_id = exec_ctx.tenant_id
            if exec_ctx.user_id:
                event.user_id = exec_ctx.user_id
            if exec_ctx.session_id:
                event.session_id = exec_ctx.session_id
            if exec_ctx.run_id:
                event.run_id = exec_ctx.run_id
        if not event.trace_id:
            _ctx = _TRACE_MGR.current()
            if _ctx is not None:
                event.trace_id = _ctx.trace_id
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO run_events
                    (event_id, run_id, sequence, event_type, payload_json,
                     tenant_id, user_id, session_id, trace_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.sequence,
                    event.event_type,
                    event.payload_json,
                    event.tenant_id,
                    event.user_id,
                    event.session_id,
                    event.trace_id,
                    event.created_at,
                ),
            )
            self._conn.commit()
        # Increment event_stored counter (secondary signal — no recursion risk).
        try:
            from hi_agent.observability.collector import get_metrics_collector
            _col = get_metrics_collector()
            if _col is not None:
                _col.increment("hi_agent_events_stored_total")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def _row_to_event(self, row: tuple) -> StoredEvent:
        # Row column order matches explicit SELECT:
        # event_id[0], run_id[1], sequence[2], event_type[3], payload_json[4],
        # tenant_id[5], user_id[6], session_id[7], trace_id[8], created_at[9]
        return StoredEvent(
            event_id=row[0],
            run_id=row[1],
            sequence=row[2],
            event_type=row[3],
            payload_json=row[4],
            tenant_id=row[5],
            user_id=row[6],
            session_id=row[7],
            trace_id=row[8],
            created_at=row[9],
        )

    def list_since(
        self,
        run_id: str,
        since_sequence: int = 0,
        *,
        last_id: int | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[StoredEvent]:
        """Return events for *run_id* after the requested sequence.

        Args:
            run_id: Run identifier.
            since_sequence: Positional sequence cursor kept for backward compatibility.
            last_id: Alias for since_sequence when called with keyword syntax.
            tenant_id: Optional workspace filter.
            user_id: Optional workspace filter.
            session_id: Optional workspace filter.
        """
        threshold = last_id if last_id is not None else since_sequence
        query = (
            "SELECT event_id, run_id, sequence, event_type, payload_json, "
            "tenant_id, user_id, session_id, trace_id, created_at "
            "FROM run_events WHERE run_id = ? AND sequence > ?"
        )
        params: list = [run_id, threshold]
        if tenant_id is not None:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY sequence ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_events(
        self,
        run_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Return paginated events for *run_id* as plain dicts.

        Ordered by ascending row id (insertion order).  Suitable for
        non-SSE snapshot replay via the ``GET /runs/{run_id}/events`` endpoint.

        Args:
            run_id: Run identifier.
            offset: Number of rows to skip (0-based).
            limit: Maximum number of rows to return.

        Returns:
            List of dicts with keys matching StoredEvent fields.
        """
        query = (
            "SELECT event_id, run_id, sequence, event_type, payload_json, "
            "tenant_id, user_id, session_id, trace_id, created_at "
            "FROM run_events WHERE run_id = ? ORDER BY id ASC LIMIT ? OFFSET ?"
        )
        with self._lock:
            rows = self._conn.execute(query, (run_id, limit, offset)).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "event_id": row[0],
                    "run_id": row[1],
                    "sequence": row[2],
                    "event_type": row[3],
                    "payload_json": row[4],
                    "tenant_id": row[5],
                    "user_id": row[6],
                    "session_id": row[7],
                    "trace_id": row[8],
                    "created_at": row[9],
                }
            )
        return result

    def max_sequence(self, run_id: str) -> int:
        """Return the highest stored sequence for run_id, or -1 if none.

        Callers use ``max_sequence(run_id) + 1`` as the seed for the next
        sequence number.  Returning -1 when no events exist means the first
        event will receive sequence 0.

        Args:
            run_id: Run identifier to query.

        Returns:
            Highest sequence number stored for this run, or -1 if no events
            exist for this run_id.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(sequence) FROM run_events WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None or row[0] is None:
            return -1
        return int(row[0])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()
