"""ExperimentStore: Protocol + InMemory (dev) + SQLite (research/prod).

Factory: make_experiment_store(posture, data_dir) -> ExperimentStore.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from hi_agent.evolve.contracts import EvolutionTrial


@runtime_checkable
class ExperimentStore(Protocol):
    """Persistence contract for EvolutionTrial records."""

    def start_experiment(self, exp: EvolutionTrial) -> None:
        """Persist a new trial record."""
        ...

    def list_active(self, tenant_id: str) -> list[EvolutionTrial]:
        """Return all active trials for the given tenant."""
        ...

    def complete_experiment(self, experiment_id: str, status: str) -> None:
        """Update the status of a trial to completed or aborted."""
        ...

    def get_experiment(self, experiment_id: str) -> EvolutionTrial | None:
        """Return trial by ID, or None if not found."""
        ...


class InMemoryExperimentStore:
    """In-memory ExperimentStore for dev posture.

    State is not durable across process restarts.
    """

    def __init__(self) -> None:
        self._records: dict[str, EvolutionTrial] = {}

    def start_experiment(self, exp: EvolutionTrial) -> None:
        self._records[exp.experiment_id] = exp

    def list_active(self, tenant_id: str) -> list[EvolutionTrial]:
        return [
            r
            for r in self._records.values()
            if r.status == "active" and r.tenant_id == tenant_id
        ]

    def complete_experiment(self, experiment_id: str, status: str) -> None:
        record = self._records.get(experiment_id)
        if record is not None:
            self._records[experiment_id] = EvolutionTrial(
                experiment_id=record.experiment_id,
                capability_name=record.capability_name,
                baseline_version=record.baseline_version,
                candidate_version=record.candidate_version,
                metric_name=record.metric_name,
                started_at=record.started_at,
                status=status,
                tenant_id=record.tenant_id,
                project_id=record.project_id,
                run_id=record.run_id,
            )

    def get_experiment(self, experiment_id: str) -> EvolutionTrial | None:
        return self._records.get(experiment_id)


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS evolution_experiments (
    experiment_id   TEXT PRIMARY KEY,
    capability_name TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    candidate_version TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    status          TEXT NOT NULL,
    tenant_id       TEXT NOT NULL DEFAULT '',
    project_id      TEXT NOT NULL DEFAULT '',
    run_id          TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL
)
"""


def _row_to_experiment(row: tuple) -> EvolutionTrial:
    (
        experiment_id,
        capability_name,
        baseline_version,
        candidate_version,
        metric_name,
        started_at,
        status,
        tenant_id,
        project_id,
        run_id,
        _updated_at,
    ) = row
    return EvolutionTrial(
        experiment_id=experiment_id,
        capability_name=capability_name,
        baseline_version=baseline_version,
        candidate_version=candidate_version,
        metric_name=metric_name,
        started_at=started_at,
        status=status,
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
    )


class SqliteExperimentStore:
    """SQLite-backed ExperimentStore for research/prod posture.

    State survives process restarts; each write commits immediately.
    All list_active queries filter by tenant_id (tenant isolation).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def start_experiment(self, exp: EvolutionTrial) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evolution_experiments
                    (experiment_id, capability_name, baseline_version,
                     candidate_version, metric_name, started_at, status,
                     tenant_id, project_id, run_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp.experiment_id,
                    exp.capability_name,
                    exp.baseline_version,
                    exp.candidate_version,
                    exp.metric_name,
                    exp.started_at,
                    exp.status,
                    exp.tenant_id,
                    exp.project_id,
                    exp.run_id,
                    now,
                ),
            )
            conn.commit()

    def list_active(self, tenant_id: str) -> list[EvolutionTrial]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT experiment_id, capability_name, baseline_version,
                       candidate_version, metric_name, started_at, status,
                       tenant_id, project_id, run_id, updated_at
                FROM evolution_experiments
                WHERE status = 'active' AND tenant_id = ?
                """,
                (tenant_id,),
            ).fetchall()
        return [_row_to_experiment(row) for row in rows]

    def complete_experiment(self, experiment_id: str, status: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE evolution_experiments SET status = ?, updated_at = ? "
                "WHERE experiment_id = ?",
                (status, now, experiment_id),
            )
            conn.commit()

    def get_experiment(self, experiment_id: str) -> EvolutionTrial | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT experiment_id, capability_name, baseline_version,
                       candidate_version, metric_name, started_at, status,
                       tenant_id, project_id, run_id, updated_at
                FROM evolution_experiments
                WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_experiment(row)


def make_experiment_store(posture: object, data_dir: str) -> ExperimentStore:
    """Factory: returns InMemory for dev, SQLite for research/prod.

    Args:
        posture: A Posture instance (or any object with .is_strict).
        data_dir: Directory for the SQLite database file (research/prod only).

    Returns:
        An ExperimentStore appropriate for the given posture.
    """
    if getattr(posture, "is_strict", False):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        db_path = str(Path(data_dir) / "experiments.db")
        return SqliteExperimentStore(db_path=db_path)
    return InMemoryExperimentStore()
