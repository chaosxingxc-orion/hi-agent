"""SQLite-backed handle persistence for long-running operations (G-8)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OpStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OpHandle:
    op_id: str
    backend: str
    external_id: str
    submitted_at: float
    status: OpStatus = OpStatus.PENDING
    artifacts_uri: str = ""
    heartbeat_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""

    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = OpStatus(self.status)


class LongRunningOpStore:
    _CREATE = """
    CREATE TABLE IF NOT EXISTS ops (
        op_id        TEXT PRIMARY KEY,
        backend      TEXT NOT NULL,
        external_id  TEXT NOT NULL,
        submitted_at REAL NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        artifacts_uri TEXT DEFAULT '',
        heartbeat_at REAL DEFAULT 0,
        completed_at REAL DEFAULT 0,
        error        TEXT DEFAULT '',
        tenant_id    TEXT DEFAULT '',
        user_id      TEXT DEFAULT '',
        session_id   TEXT DEFAULT '',
        project_id   TEXT DEFAULT ''
    )
    """

    _SPINE_COLUMNS = ("tenant_id", "user_id", "session_id", "project_id")

    def __init__(self, db_path: Path):
        self._db = str(db_path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(self._CREATE)
            existing = {row[1] for row in conn.execute("PRAGMA table_info(ops)").fetchall()}
            for col in self._SPINE_COLUMNS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE ops ADD COLUMN {col} TEXT DEFAULT ''")
            conn.commit()

    def create(
        self,
        *,
        op_id: str,
        backend: str,
        external_id: str,
        submitted_at: float,
        tenant_id: str = "",
        user_id: str = "",
        session_id: str = "",
        project_id: str = "",
    ) -> OpHandle:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO ops (op_id, backend, external_id, submitted_at,"
                " tenant_id, user_id, session_id, project_id)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    op_id,
                    backend,
                    external_id,
                    submitted_at,
                    tenant_id,
                    user_id,
                    session_id,
                    project_id,
                ),
            )
            conn.commit()
        return OpHandle(
            op_id=op_id,
            backend=backend,
            external_id=external_id,
            submitted_at=submitted_at,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
        )

    def get(self, op_id: str) -> OpHandle | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM ops WHERE op_id=?", (op_id,)).fetchone()
        if row is None:
            return None
        return OpHandle(**dict(row))

    def update_status(self, op_id: str, status: OpStatus, **kwargs) -> None:
        sets = ["status=?"]
        vals: list = [status.value]
        for k, v in kwargs.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(op_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE ops SET {', '.join(sets)} WHERE op_id=?", vals)
            conn.commit()

    def list_active(self) -> list[OpHandle]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ops WHERE status IN ('pending','running')"
            ).fetchall()
        return [OpHandle(**dict(r)) for r in rows]
