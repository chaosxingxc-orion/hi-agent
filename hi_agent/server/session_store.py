"""SQLite-backed session store for durable session state persistence.

Provides CRUD operations for user sessions with ownership validation.

W32 Track B Gap 4: the unscoped admin accessor previously exposed as
``SessionStore.get_unsafe`` has been removed from the public class. Admin
tooling that legitimately needs cross-tenant reads must import
``admin_get_session`` from ``hi_agent.server._admin_session_store``. This
prevents the unscoped accessor from being reachable from tenant-facing
code paths via attribute access on the public store.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext


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
    tenant_id    TEXT    NOT NULL,
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
        # Track D C-1: WAL + busy_timeout via shared helper.
        from hi_agent._sqlite_init import configure_sqlite_connection
        configure_sqlite_connection(self._conn)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _cx(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SessionStore not initialized — call initialize() first")
        return self._conn

    def create(
        self,
        tenant_id: str,
        user_id: str,
        team_id: str = "",
        name: str = "",
        *,
        exec_ctx: RunExecutionContext | None = None,
    ) -> str:
        """Create a new session and return its ID.

        Args:
            tenant_id: Tenant/workspace identifier.
            user_id: User identifier.
            team_id: Optional team identifier.
            name: Optional session name.
            exec_ctx: Optional RunExecutionContext; when provided, tenant_id
                and user_id are derived from exec_ctx when the caller's own
                values are empty. exec_ctx fields take precedence for spine.

        Returns:
            Newly generated session ID (UUID4).
        """
        if exec_ctx is not None:
            if exec_ctx.tenant_id:
                tenant_id = exec_ctx.tenant_id
            if exec_ctx.user_id:
                user_id = exec_ctx.user_id
        sid = str(uuid.uuid4())
        with self._lock:
            self._cx().execute(
                "INSERT INTO sessions (session_id, tenant_id, user_id, team_id, name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, tenant_id, user_id, team_id, name, time.time()),
            )
            self._cx().commit()
        return sid

    # W32 Track B Gap 4: the public ``get_unsafe`` accessor has been removed.
    # Admin tooling that legitimately needs cross-tenant reads MUST import
    # ``admin_get_session`` from ``hi_agent.server._admin_session_store`` and
    # call it explicitly. The helper below is private to support the admin
    # module without exposing an unscoped public method on this class.
    # scope: process-internal — admin shim
    def _admin_internal_get(self, session_id: str) -> SessionRecord | None:
        """INTERNAL: cross-tenant fetch by session_id; admin module ONLY.

        # scope: process-internal -- admin only

        DO NOT call from tenant-facing code paths. Public callers MUST use
        :meth:`get_for_tenant` instead. The single legitimate caller is
        :func:`hi_agent.server._admin_session_store.admin_get_session`,
        which is gated by an import-allowlist in CI.
        """
        row = (
            self._cx()
            .execute(
                "SELECT session_id, tenant_id, user_id, team_id, name, status, "
                "created_at, archived_at FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            .fetchone()
        )
        return self._row(row) if row else None

    def get_for_tenant(
        self, session_id: str, tenant_id: str
    ) -> SessionRecord | None:
        """Retrieve a session by ID, scoped to a single tenant.

        Returns ``None`` both when the session does not exist and when it
        exists in a different tenant. Callers MUST NOT distinguish between
        these two cases — doing so would reveal cross-tenant existence.

        Args:
            session_id: Session identifier.
            tenant_id: Tenant identifier the caller's request is scoped to.

        Returns:
            SessionRecord if a session with this id exists in ``tenant_id``,
            None otherwise (including when the id exists in another tenant).
        """
        row = (
            self._cx()
            .execute(
                "SELECT session_id, tenant_id, user_id, team_id, name, status, "
                "created_at, archived_at FROM sessions "
                "WHERE session_id = ? AND tenant_id = ?",
                (session_id, tenant_id),
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
                "SELECT 1 FROM sessions WHERE session_id = ? AND tenant_id = ? "
                "AND user_id = ? AND status = 'active'",
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
                "SELECT session_id, tenant_id, user_id, team_id, name, status, "
                "created_at, archived_at FROM sessions WHERE tenant_id = ? AND "
                "user_id = ? AND status = 'active' ORDER BY created_at DESC",
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
                "WHERE session_id = ? AND tenant_id = ? AND user_id = ? AND "
                "status = 'active'",
                (time.time(), session_id, tenant_id, user_id),
            )
            self._cx().commit()
            if cur.rowcount == 0:
                raise PermissionError(
                    f"session {session_id} not owned by {tenant_id}/{user_id} or already archived"
                )

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
