"""SQLite-backed registry of active team runs.

RO-4: replaces the in-memory dict with a durable SQLite store that survives
process restarts under research/prod posture.  Under dev posture the store
defaults to ``:memory:`` for backward compatibility.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import ClassVar

from hi_agent.contracts.team_runtime import TeamRun


def _resolve_team_registry_path(db_path: str | None) -> str:
    """Resolve the SQLite path for TeamRunRegistry based on posture.

    - dev  → ``:memory:`` (ephemeral, backward-compatible)
    - research/prod → file-backed path from ``HI_AGENT_DATA_DIR`` env var
      (or ``./hi_agent_data/team_run_registry.sqlite``).
    """
    if db_path is not None:
        return db_path
    try:
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if not posture.requires_durable_registry:
            return ":memory:"
    except (ValueError, OSError):
        return ":memory:"

    import os

    data_dir = os.environ.get("HI_AGENT_DATA_DIR", "./hi_agent_data")
    return str(Path(data_dir) / "team_run_registry.sqlite")


class TeamRunRegistry:
    """SQLite-backed registry of active team runs.

    Provides O(1) lookup of team membership by team_id with thread-safe,
    durable storage.  Under dev posture defaults to ``:memory:``.

    Serialization: TeamRun fields are stored as JSON columns; member_runs is
    a JSON array of [role_id, run_id] pairs.
    """

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS team_runs (
    team_id     TEXT    PRIMARY KEY,
    pi_run_id   TEXT    NOT NULL DEFAULT '',
    project_id  TEXT    NOT NULL DEFAULT '',
    member_runs TEXT    NOT NULL DEFAULT '[]',
    created_at  TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'created',
    finished_at REAL    NOT NULL DEFAULT 0,
    tenant_id   TEXT    NOT NULL DEFAULT '',
    user_id     TEXT    NOT NULL DEFAULT '',
    session_id  TEXT    NOT NULL DEFAULT ''
)
"""

    _MIGRATE_COLS: ClassVar[list[str]] = [
        "ALTER TABLE team_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'created'",
        "ALTER TABLE team_runs ADD COLUMN finished_at REAL NOT NULL DEFAULT 0",
        "ALTER TABLE team_runs ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE team_runs ADD COLUMN user_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE team_runs ADD COLUMN session_id TEXT NOT NULL DEFAULT ''",
    ]

    def __init__(self, db_path: str | None = None) -> None:
        """Open (or create) the team run registry database.

        RO-4: When ``db_path`` is ``None`` the path is resolved from posture:
        - dev  → ``:memory:``
        - research/prod → file-backed path.

        Args:
            db_path: Explicit path, ``":memory:"``, or ``None`` for
                posture-resolved default.
        """
        resolved = _resolve_team_registry_path(db_path)
        self.db_path = resolved  # expose for inspection in tests

        if resolved != ":memory:":
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(resolved, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add status and finished_at columns to team_runs table if missing."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(team_runs)")}
        for stmt in self._MIGRATE_COLS:
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            if col not in cols:
                self._conn.execute(stmt)
        self._conn.commit()

    # -- serialization helpers -----------------------------------------------

    def _to_row(self, team_run: TeamRun) -> tuple:
        member_json = json.dumps(list(team_run.member_runs))
        return (
            team_run.team_id,
            team_run.pi_run_id,
            team_run.project_id,
            member_json,
            team_run.created_at,
            "created",
            0.0,
            team_run.tenant_id,
            team_run.user_id,
            team_run.session_id,
        )

    def _from_row(self, row: tuple) -> TeamRun:
        (
            team_id,
            pi_run_id,
            project_id,
            member_json,
            created_at,
            tenant_id,
            user_id,
            session_id,
        ) = (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
        raw_members = json.loads(member_json) if member_json else []
        member_runs = tuple(tuple(pair) for pair in raw_members)
        return TeamRun(
            team_id=team_id,
            pi_run_id=pi_run_id,
            project_id=project_id,
            member_runs=member_runs,
            created_at=created_at,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
        )

    # -- public API ----------------------------------------------------------

    def register(self, team_run: TeamRun) -> None:
        """Register or replace a TeamRun in the registry.

        Rule 12 — Contract Spine: under research/prod posture, ``tenant_id`` is
        required.  A TeamRun with empty ``tenant_id`` raises ``ValueError`` so
        cross-tenant audit trails cannot silently lose attribution.  Under dev
        posture an empty tenant_id is permitted for backward-compatible tests.

        Args:
            team_run: TeamRun to register. Replaces any existing entry for
                the same team_id.

        Raises:
            ValueError: research/prod posture and ``team_run.tenant_id`` empty.
        """
        from hi_agent.config.posture import Posture

        posture = Posture.from_env()
        if posture.is_strict and not team_run.tenant_id:
            raise ValueError(
                "TeamRun.tenant_id is required under research/prod posture "
                "(Rule 12 — Contract Spine)"
            )
        row = self._to_row(team_run)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO team_runs "
                "(team_id, pi_run_id, project_id, member_runs, created_at, "
                "status, finished_at, tenant_id, user_id, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            self._conn.commit()

    def get(self, team_id: str) -> TeamRun | None:
        """Return the TeamRun for team_id, or None if not registered.

        Args:
            team_id: Team identifier.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT team_id, pi_run_id, project_id, member_runs, "
                "created_at, tenant_id, user_id, session_id "
                "FROM team_runs WHERE team_id = ?",
                (team_id,),
            )
            row = cur.fetchone()
        return self._from_row(row) if row else None

    def list_members(self, team_id: str) -> list[tuple[str, str]]:
        """Return the (role_id, run_id) member pairs for a team.

        Args:
            team_id: Team identifier.

        Returns:
            List of (role_id, run_id) tuples, or empty list if not found.
        """
        run = self.get(team_id)
        return list(run.member_runs) if run else []

    def unregister(self, team_id: str) -> None:
        """Remove a team from the registry.

        Args:
            team_id: Team identifier. No-op if not present.
        """
        with self._lock:
            self._conn.execute("DELETE FROM team_runs WHERE team_id = ?", (team_id,))
            self._conn.commit()

    def set_status(self, team_id: str, status: str, finished_at: float | None = None) -> None:
        """Update the status of a team run.

        Args:
            team_id: Team identifier.
            status: New status value (e.g. 'running', 'completed', 'failed', 'cancelled').
            finished_at: Explicit finished_at epoch timestamp. When None, auto-set for
                terminal states (completed/failed/cancelled) and left 0 for non-terminal.
        """
        import time as _time
        now = _time.time()
        ft = finished_at if finished_at is not None else (
            now if status in ("completed", "failed", "cancelled") else 0.0
        )
        with self._lock:
            self._conn.execute(
                "UPDATE team_runs SET status = ?, finished_at = ? WHERE team_id = ?",
                (status, ft, team_id),
            )
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
