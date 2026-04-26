import sqlite3
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext


@dataclass
class TeamEvent:
    event_id: str
    tenant_id: str
    team_space_id: str
    event_type: str
    payload_json: str
    source_run_id: str
    source_user_id: str
    source_session_id: str
    publish_reason: str
    schema_version: int
    created_at: float
    project_id: str = field(default="")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT    NOT NULL UNIQUE,
    tenant_id       TEXT    NOT NULL,
    team_space_id   TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL DEFAULT '{}',
    source_run_id   TEXT    NOT NULL DEFAULT '',
    source_user_id  TEXT    NOT NULL DEFAULT '',
    source_session_id TEXT  NOT NULL DEFAULT '',
    publish_reason  TEXT    NOT NULL DEFAULT '',
    schema_version  INTEGER NOT NULL DEFAULT 1,
    created_at      REAL    NOT NULL DEFAULT 0.0,
    project_id      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_team_events_space
  ON team_events (tenant_id, team_space_id, id);
CREATE INDEX IF NOT EXISTS idx_team_events_type
  ON team_events (tenant_id, team_space_id, event_type, id);
"""

_SELECT_COLS = (
    "event_id, tenant_id, team_space_id, event_type, payload_json, "
    "source_run_id, source_user_id, source_session_id, "
    "publish_reason, schema_version, created_at, project_id"
)


class TeamEventStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _cx(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("TeamEventStore not initialized")
        return self._conn

    def insert(self, event: TeamEvent, *, exec_ctx: RunExecutionContext | None = None) -> None:
        if exec_ctx is not None:
            if not event.tenant_id:
                event.tenant_id = exec_ctx.tenant_id
            if not event.project_id:
                event.project_id = exec_ctx.project_id
        with self._lock:
            self._cx().execute(
                "INSERT OR IGNORE INTO team_events "
                "(event_id, tenant_id, team_space_id, event_type, payload_json, "
                "source_run_id, source_user_id, source_session_id, "
                "publish_reason, schema_version, created_at, project_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.tenant_id,
                    event.team_space_id,
                    event.event_type,
                    event.payload_json,
                    event.source_run_id,
                    event.source_user_id,
                    event.source_session_id,
                    event.publish_reason,
                    event.schema_version,
                    event.created_at,
                    event.project_id,
                ),
            )
            self._cx().commit()

    def list_since(self, tenant_id: str, team_space_id: str, since_id: int = 0) -> list[TeamEvent]:
        rows = (
            self._cx()
            .execute(
                f"SELECT {_SELECT_COLS} "
                "FROM team_events WHERE tenant_id=? AND team_space_id=? AND id>? "
                "ORDER BY id",
                (tenant_id, team_space_id, since_id),
            )
            .fetchall()
        )
        return [TeamEvent(*r) for r in rows]

    def list(
        self,
        tenant_id: str,
        team_space_id: str,
        *,
        since_id: int = 0,
        event_types: list[str] | None = None,
        source_run_ids: list[str] | None = None,
        limit: int | None = None,
        order: str = "asc",
    ) -> list[TeamEvent]:
        """Query team events with optional filters, ordering, and limit.

        Args:
            tenant_id: Tenant scope.
            team_space_id: Team space scope.
            since_id: Only return events with internal id > since_id.
            event_types: Whitelist of event_type values (OR logic).
            source_run_ids: Whitelist of source_run_id values (OR logic).
            limit: Maximum number of events to return.
            order: ``"asc"`` (default, oldest first) or ``"desc"`` (newest first).

        Returns:
            List of :class:`TeamEvent` objects matching all filters.
        """
        where_clauses = ["tenant_id=? AND team_space_id=? AND id>?"]
        params: list = [tenant_id, team_space_id, since_id]

        if event_types:
            ph = ",".join("?" * len(event_types))
            where_clauses.append(f"event_type IN ({ph})")
            params.extend(event_types)

        if source_run_ids:
            ph = ",".join("?" * len(source_run_ids))
            where_clauses.append(f"source_run_id IN ({ph})")
            params.extend(source_run_ids)

        order_dir = "ASC" if order.lower() == "asc" else "DESC"
        limit_clause = f" LIMIT {int(limit)}" if limit is not None else ""
        sql = (
            f"SELECT {_SELECT_COLS} FROM team_events "
            f"WHERE {' AND '.join(where_clauses)} "
            f"ORDER BY id {order_dir}{limit_clause}"
        )
        rows = self._cx().execute(sql, params).fetchall()
        return [TeamEvent(*r) for r in rows]
