"""Integration tests: EvolveEngine writes EvolutionExperiment on promotion proposals.

Uses real ChampionChallenger and real InMemoryExperimentStore.
No mocks on the subsystems under test.
"""

from __future__ import annotations

import pytest
from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import RunPostmortem
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.experiment_store import InMemoryExperimentStore
from hi_agent.evolve.regression_detector import RegressionDetector
from hi_agent.evolve.skill_extractor import SkillExtractor


def _make_postmortem(run_id: str = "run-001", skills: list[str] | None = None) -> RunPostmortem:
    return RunPostmortem(
        run_id=run_id,
        task_id="task-001",
        task_family="quick_task",
        outcome="completed",
        stages_completed=["stage1"],
        stages_failed=[],
        branches_explored=1,
        branches_pruned=0,
        total_actions=3,
        failure_codes=[],
        duration_seconds=1.5,
        quality_score=0.9,
        efficiency_score=0.8,
        skills_used=skills or [],
        tenant_id="",
    )


def test_engine_writes_experiment_on_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    """EvolveEngine writes EvolutionExperiment when challenger outperforms champion.

    Integration: real ChampionChallenger, real InMemoryExperimentStore.
    The engine records skills as champion (version="unknown") when no version_manager
    is provided.  We pre-register a challenger with a higher score so the comparison
    triggers a promote_challenger recommendation and writes an EvolutionExperiment.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    cc = ChampionChallenger()
    exp_store = InMemoryExperimentStore()

    # Pre-register a challenger with a very high score.  The engine will record
    # the champion via cc.record(..., is_challenger=False) using version="unknown"
    # and low quality.  After the engine records, the champion has quality=0.9
    # (from the postmortem) but the challenger has quality=0.99, ensuring promotion.
    cc.register_challenger("skill-routing", version="v1.1", metrics={"quality": 0.99})

    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=cc,
        experiment_store=exp_store,
        comparison_interval=1,  # trigger comparison every run
    )

    # on_run_completed: engine records skill-routing as champion (version="unknown"),
    # then compare() finds challenger score > champion score → promote_challenger.
    pm = _make_postmortem(run_id="run-001", skills=["skill-routing"])
    engine.on_run_completed(pm)

    active = exp_store.list_active("")
    assert len(active) >= 1
    exp = active[0]
    assert exp.capability_name == "skill-routing"
    assert exp.candidate_version == "v1.1"
    assert exp.status == "active"
    assert exp.run_id == "run-001"


def test_engine_default_experiment_store_is_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """EvolveEngine creates an InMemoryExperimentStore by default (backwards-compat)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=ChampionChallenger(),
    )
    assert isinstance(engine._experiment_store, InMemoryExperimentStore)
