"""Integration tests: SqliteExperimentStore restart-survival and tenant isolation."""

from __future__ import annotations

import pytest
from hi_agent.evolve.contracts import EvolutionTrial
from hi_agent.evolve.experiment_store import SqliteExperimentStore


def _make_exp(
    experiment_id: str,
    tenant_id: str,
    *,
    status: str = "active",
) -> EvolutionTrial:
    return EvolutionTrial(
        experiment_id=experiment_id,
        capability_name="skill_routing",
        baseline_version="v1.0",
        candidate_version="v1.1",
        metric_name="quality_score",
        started_at="2026-04-26T00:00:00+00:00",
        status=status,
        tenant_id=tenant_id,
        project_id="proj-1",
        run_id="run-001",
    )


def test_restart_survival(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SqliteExperimentStore: write experiment, recreate store, list_active returns it.

    Integration: real SQLite file on disk; no mocks on the subject under test.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    db_path = str(tmp_path / "experiments.db")
    exp = _make_exp("exp-001", "tenant-abc")

    store1 = SqliteExperimentStore(db_path=db_path)
    store1.start_experiment(exp)

    # Recreate from same path (simulates restart).
    store2 = SqliteExperimentStore(db_path=db_path)
    results = store2.list_active("tenant-abc")
    assert len(results) == 1
    assert results[0].experiment_id == "exp-001"
    assert results[0].tenant_id == "tenant-abc"


def test_tenant_isolation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SqliteExperimentStore: experiment written for tenant_a is not visible to tenant_b."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    db_path = str(tmp_path / "experiments.db")
    store = SqliteExperimentStore(db_path=db_path)

    store.start_experiment(_make_exp("exp-for-a", "tenant-a"))

    results_b = store.list_active("tenant-b")
    assert results_b == []

    results_a = store.list_active("tenant-a")
    assert len(results_a) == 1
    assert results_a[0].experiment_id == "exp-for-a"


def test_complete_experiment(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SqliteExperimentStore: complete_experiment removes from active list."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    db_path = str(tmp_path / "experiments.db")
    store = SqliteExperimentStore(db_path=db_path)

    store.start_experiment(_make_exp("exp-002", "tenant-abc"))
    store.complete_experiment("exp-002", "completed")

    assert store.list_active("tenant-abc") == []

    exp = store.get_experiment("exp-002")
    assert exp is not None
    assert exp.status == "completed"


def test_get_experiment_not_found(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SqliteExperimentStore.get_experiment returns None for unknown ID."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    db_path = str(tmp_path / "experiments.db")
    store = SqliteExperimentStore(db_path=db_path)
    assert store.get_experiment("no-such-id") is None
