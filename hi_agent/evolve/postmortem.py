"""PostmortemEngine: lifecycle management for ProjectRetrospective records.

Stores and retrieves ProjectRetrospective records produced when a project
completes (all runs terminal or explicit project_completed signal).

Rule 11: in-memory store under dev posture; SQLite-backed under research/prod.
Rule 12: ProjectRetrospective carries tenant_id per contract.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from hi_agent.config.posture import Posture
from hi_agent.evolve.contracts import ProjectRetrospective

logger = logging.getLogger(__name__)


class PostmortemEngine:
    """Lifecycle engine for ProjectRetrospective records.

    on_project_completed() creates and stores a ProjectRetrospective from
    the supplied retrospective data. get() retrieves a stored record by
    project_id.

    Storage is posture-aware (Rule 11):
    - dev posture: in-memory dict, not durable across restarts.
    - research/prod posture: SQLite-backed, durable across restarts.
    """

    def __init__(
        self,
        posture: Posture | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize the PostmortemEngine.

        Args:
            posture: Execution posture; defaults to Posture.from_env().
                Under research/prod, db_path is required.
            db_path: SQLite database path. Required under research/prod
                posture. Ignored under dev posture (in-memory used).

        Raises:
            ValueError: Under research/prod posture when db_path is None.
        """
        self._posture = posture if posture is not None else Posture.from_env()
        if self._posture.is_strict and not db_path:
            raise ValueError(
                "PostmortemEngine: db_path required under research/prod posture (Rule 11)"
            )
        self._db_path = db_path
        # In-memory store used under dev posture or when db_path is None.
        self._memory: dict[str, ProjectRetrospective] = {}

        if self._db_path is not None:
            self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_project_completed(
        self,
        project_id: str,
        retrospective: ProjectRetrospective,
    ) -> ProjectRetrospective:
        """Record a PostmortemEngine entry when a project completes.

        Persists the supplied ProjectRetrospective under the given
        project_id. Overwrites any prior entry for the same project_id.

        Args:
            project_id: Unique identifier of the completed project.
            retrospective: Aggregated retrospective for the project.

        Returns:
            The stored ProjectRetrospective (identical to the input).
        """
        self._store(project_id, retrospective)
        logger.info(
            "PostmortemEngine: recorded retrospective for project_id=%s run_count=%d",
            project_id,
            len(retrospective.run_ids),
        )
        return retrospective

    def get(self, project_id: str) -> ProjectRetrospective | None:
        """Retrieve a stored ProjectRetrospective by project_id.

        Args:
            project_id: Unique identifier of the project.

        Returns:
            The stored ProjectRetrospective, or None if not found.
        """
        if self._db_path is not None:
            return self._db_get(project_id)
        return self._memory.get(project_id)

    # ------------------------------------------------------------------
    # Internal: in-memory path
    # ------------------------------------------------------------------

    def _store(self, project_id: str, retro: ProjectRetrospective) -> None:
        """Persist the retrospective via the appropriate backend."""
        if self._db_path is not None:
            self._db_upsert(project_id, retro)
        else:
            self._memory[project_id] = retro

    # ------------------------------------------------------------------
    # Internal: SQLite path
    # ------------------------------------------------------------------

    _CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS project_retrospectives (
        project_id      TEXT PRIMARY KEY,
        tenant_id       TEXT NOT NULL DEFAULT '',
        run_ids_json    TEXT NOT NULL DEFAULT '[]',
        backtrack_count INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)  # type: ignore[arg-type]
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        assert self._db_path is not None
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(self._CREATE_TABLE)
            conn.commit()

    def _db_upsert(self, project_id: str, retro: ProjectRetrospective) -> None:
        import json

        now = datetime.now(UTC).isoformat()
        run_ids_json = json.dumps(retro.run_ids)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO project_retrospectives
                    (project_id, tenant_id, run_ids_json,
                     backtrack_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    retro.tenant_id,
                    run_ids_json,
                    retro.backtrack_count,
                    retro.created_at or now,
                    now,
                ),
            )
            conn.commit()

    def _db_get(self, project_id: str) -> ProjectRetrospective | None:
        import json

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT project_id, tenant_id, run_ids_json,
                       backtrack_count, created_at
                FROM project_retrospectives
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        (proj_id, tenant_id, run_ids_json, backtrack_count, created_at) = row
        return ProjectRetrospective(
            project_id=proj_id,
            run_ids=json.loads(run_ids_json),
            backtrack_count=backtrack_count,
            created_at=created_at,
            tenant_id=tenant_id,
        )


def make_postmortem_engine(posture: Posture, data_dir: str | None) -> PostmortemEngine:
    """Factory: construct a PostmortemEngine appropriate for the given posture.

    Args:
        posture: Execution posture (dev / research / prod).
        data_dir: Directory for SQLite file under research/prod posture.
            Must be non-empty when posture.is_strict is True.

    Returns:
        A PostmortemEngine with the appropriate storage backend.
    """
    if posture.is_strict:
        if not data_dir:
            raise ValueError(
                "make_postmortem_engine: data_dir required under research/prod posture"
            )
        db_path = str(Path(data_dir) / "postmortems.db")
        return PostmortemEngine(posture=posture, db_path=db_path)
    return PostmortemEngine(posture=posture, db_path=None)
