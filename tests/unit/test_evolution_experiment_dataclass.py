"""Unit tests: EvolutionTrial dataclass posture enforcement (W18: EvolutionExperiment removed)."""

from __future__ import annotations

import pytest
from hi_agent.evolve.contracts import EvolutionTrial


def _make_trial(**overrides) -> EvolutionTrial:
    kwargs: dict = {
        "experiment_id": "exp-001",
        "capability_name": "skill_routing",
        "baseline_version": "v1.0",
        "candidate_version": "v1.1",
        "metric_name": "quality_score",
        "started_at": "2026-04-26T00:00:00+00:00",
        "status": "active",
    }
    kwargs.update(overrides)
    return EvolutionTrial(**kwargs)


def test_research_rejects_missing_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """EvolutionTrial with empty tenant_id must raise ValueError under research posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    with pytest.raises(ValueError, match="tenant_id"):
        _make_trial(tenant_id="")


def test_dev_allows_missing_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """EvolutionTrial with empty tenant_id must succeed under dev posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    exp = _make_trial(tenant_id="")
    assert exp.tenant_id == ""


def test_valid_trial_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Well-formed EvolutionTrial should construct successfully under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    exp = _make_trial(
        tenant_id="tenant-abc",
        project_id="proj-123",
        run_id="run-001",
    )
    assert exp.experiment_id == "exp-001"
    assert exp.capability_name == "skill_routing"
    assert exp.baseline_version == "v1.0"
    assert exp.candidate_version == "v1.1"
    assert exp.metric_name == "quality_score"
    assert exp.status == "active"
    assert exp.tenant_id == "tenant-abc"
    assert exp.project_id == "proj-123"
    assert exp.run_id == "run-001"


def test_default_spine_fields_are_empty_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional spine fields default to empty string under dev posture."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    exp = _make_trial()
    assert exp.tenant_id == ""
    assert exp.project_id == ""
    assert exp.run_id == ""
