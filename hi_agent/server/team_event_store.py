import sqlite3
import threading
from dataclasses import dataclass


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
    created_at      REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_team_events_space
  ON team_events (tenant_id, team_space_id, id);
"""


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

    def insert(self, event: TeamEvent) -> None:
        with self._lock:
            self._cx().execute(
                "INSERT OR IGNORE INTO team_events "
                "(event_id, tenant_id, team_space_id, event_type, payload_json, "
                "source_run_id, source_user_id, source_session_id, "
                "publish_reason, schema_version, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (event.event_id, event.tenant_id, event.team_space_id,
                 event.event_type, event.payload_json, event.source_run_id,
                 event.source_user_id, event.source_session_id,
                 event.publish_reason, event.schema_version, event.created_at),
            )
            self._cx().commit()

    def list_since(self, tenant_id: str, team_space_id: str, since_id: int = 0) -> list[TeamEvent]:
        rows = self._cx().execute(
            "SELECT event_id, tenant_id, team_space_id, event_type, payload_json, "
            "source_run_id, source_user_id, source_session_id, "
            "publish_reason, schema_version, created_at "
            "FROM team_events WHERE tenant_id=? AND team_space_id=? AND id>? "
            "ORDER BY id",
            (tenant_id, team_space_id, since_id),
        ).fetchall()
        return [TeamEvent(*r) for r in rows]
