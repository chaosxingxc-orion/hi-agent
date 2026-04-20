"""SQLite-backed session store for durable session state persistence.

Provides CRUD operations for user sessions with ownership validation.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionRecord:
    """Persistent record for a single session."""

    session_id: str
    tenant_id: str
    user_id: str
    team_id: str
    name: str
    status: str  # "active" | "archived"
    created_at: float
    archived_at: float | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT    PRIMARY KEY,
    tenant_id    TEXT    NOT NULL DEFAULT '',
    user_id      TEXT    NOT NULL DEFAULT '',
    team_id      TEXT    NOT NULL DEFAULT '',
    name         TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'active',
    created_at   REAL    NOT NULL DEFAULT 0.0,
    archived_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace
  ON sessions (tenant_id, user_id, status, created_at);
"""


class SessionStore:
    """SQLite-backed store for durable session records.

    Thread-safe via ``check_same_thread=False`` plus an explicit
    ``threading.Lock`` that serializes all writes.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Open (or create) the session database.

        Args:
            db_path: Filesystem path for the SQLite file.
        """
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Initialize the database and create schema."""
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _cx(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SessionStore not initialized — call initialize() first")
        return self._conn

    def create(self, tenant_id: str, user_id: str, team_id: str = "", name: str = "") -> str:
        """Create a new session and return its ID.

        Args:
            tenant_id: Tenant/workspace identifier.
            user_id: User identifier.
            team_id: Optional team identifier.
            name: Optional session name.

        Returns:
            Newly generated session ID (UUID4).
        """
        sid = str(uuid.uuid4())
        with self._lock:
            self._cx().execute(
                "INSERT INTO sessions (session_id, tenant_id, user_id, team_id, name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, tenant_id, user_id, team_id, name, time.time()),
            )
            self._cx().commit()
        return sid

    def get(self, session_id: str) -> SessionRecord | None:
        """Retrieve a session by ID.

        Args:
            session_id: Session identifier.

        Returns:
            SessionRecord if found, None otherwise.
        """
        row = (
            self._cx()
            .execute(
                "SELECT session_id, tenant_id, user_id, team_id, name, status, created_at, archived_at "
                "FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            .fetchone()
        )
        return self._row(row) if row else None

    def validate_ownership(self, session_id: str, tenant_id: str, user_id: str) -> bool:
        """Check if a session is owned by a specific tenant/user.

        Args:
            session_id: Session identifier.
            tenant_id: Tenant identifier.
            user_id: User identifier.

        Returns:
            True if the session is owned by the tenant/user, False otherwise.
        """
        row = (
            self._cx()
            .execute(
                "SELECT 1 FROM sessions WHERE session_id = ? AND tenant_id = ? AND user_id = ? AND status = 'active'",
                (session_id, tenant_id, user_id),
            )
            .fetchone()
        )
        return row is not None

    def list_active(self, tenant_id: str, user_id: str) -> list[SessionRecord]:
        """List all active sessions for a tenant/user.

        Args:
            tenant_id: Tenant identifier.
            user_id: User identifier.

        Returns:
            List of active SessionRecords, ordered by creation time (newest first).
        """
        rows = (
            self._cx()
            .execute(
                "SELECT session_id, tenant_id, user_id, team_id, name, status, created_at, archived_at "
                "FROM sessions WHERE tenant_id = ? AND user_id = ? AND status = 'active' "
                "ORDER BY created_at DESC",
                (tenant_id, user_id),
            )
            .fetchall()
        )
        return [self._row(r) for r in rows]

    def archive(self, session_id: str, tenant_id: str, user_id: str) -> None:
        """Archive a session (mark as inactive).

        Args:
            session_id: Session identifier.
            tenant_id: Tenant identifier.
            user_id: User identifier.

        Raises:
            PermissionError: If the session is not owned by the tenant/user.
        """
        with self._lock:
            cur = self._cx().execute(
                "UPDATE sessions SET status = 'archived', archived_at = ? "
                "WHERE session_id = ? AND tenant_id = ? AND user_id = ? AND status = 'active'",
                (time.time(), session_id, tenant_id, user_id),
            )
            self._cx().commit()
            if cur.rowcount == 0:
                raise PermissionError(
                    f"session {session_id} not owned by {tenant_id}/{user_id} or already archived"
                )

    def close(self) -> None:
        """Close the underlying database connection if initialized."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __del__(self) -> None:
        """Best-effort close for short-lived stores in tests and scripts."""
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _row(row: tuple) -> SessionRecord:
        """Convert a database row tuple to a SessionRecord."""
        return SessionRecord(
            session_id=row[0],
            tenant_id=row[1],
            user_id=row[2],
            team_id=row[3],
            name=row[4],
            status=row[5],
            created_at=row[6],
            archived_at=row[7],
        )
