"""Tests for EvolveEngine champion/challenger wiring."""

from __future__ import annotations

from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import RunRetrospective
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.regression_detector import RegressionDetector
from hi_agent.evolve.skill_extractor import SkillExtractor
from hi_agent.skill.version import SkillVersionManager


def _make_postmortem(
    run_id: str = "run-1",
    quality: float | None = 0.8,
    efficiency: float | None = 0.7,
    skills_used: list[str] | None = None,
) -> RunRetrospective:
    return RunRetrospective(
        run_id=run_id,
        task_id="task-1",
        task_family="general",
        outcome="completed",
        stages_completed=["S1"],
        stages_failed=[],
        branches_explored=1,
        branches_pruned=0,
        total_actions=1,
        failure_codes=[],
        duration_seconds=10.0,
        quality_score=quality,
        efficiency_score=efficiency,
        skills_used=skills_used or [],
    )


class TestChampionChallengerDirect:
    """Direct ChampionChallenger tests."""

    def test_metrics_recorded(self):
        cc = ChampionChallenger()
        cc.record("skill-A", "v1", {"quality": 0.8}, is_challenger=False)
        assert cc.get_run_count("skill-A") == 1

    def test_comparison_triggers(self):
        cc = ChampionChallenger()
        cc.register_champion("skill-A", "v1", {"quality": 0.7})
        cc.register_challenger("skill-A", "v2", {"quality": 0.9})
        result = cc.compare("skill-A")
        assert result.winner == "challenger"
        assert result.recommendation == "promote_challenger"

    def test_no_promotion_without_challenger(self):
        cc = ChampionChallenger()
        cc.register_champion("skill-A", "v1", {"quality": 0.8})
        result = cc.compare("skill-A")
        assert result.recommendation == "need_more_data"
        assert result.winner == "inconclusive"

    def test_scopes_with_challenger(self):
        cc = ChampionChallenger()
        cc.register_champion("s1", "v1", {"q": 0.5})
        cc.register_challenger("s1", "v2", {"q": 0.9})
        cc.register_champion("s2", "v1", {"q": 0.5})
        assert cc.scopes_with_challenger() == ["s1"]


class TestEvolveEngineChampionWiring:
    """EvolveEngine integration with champion/challenger."""

    def test_auto_promote(self):
        vm = SkillVersionManager()
        vm.create_version("skill-A", "champion prompt")
        vm.set_champion("skill-A", "v1")
        vm.create_version("skill-A", "challenger prompt")
        vm.set_challenger("skill-A", "v2")

        cc = ChampionChallenger()
        cc.register_champion("skill-A", "v1", {"quality": 0.5})
        cc.register_challenger("skill-A", "v2", {"quality": 0.9})

        engine = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=RegressionDetector(),
            champion_challenger=cc,
            version_manager=vm,
            comparison_interval=1,
        )
        pm = _make_postmortem(skills_used=["skill-A"])
        result = engine.on_run_completed(pm)

        promo_changes = [
            c for c in result.changes if c.change_type == "champion_challenger_promotion"
        ]
        assert len(promo_changes) == 1

    def test_broken_challenger_doesnt_crash(self):
        cc = ChampionChallenger()

        engine = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=RegressionDetector(),
            champion_challenger=cc,
            comparison_interval=1,
        )
        pm = _make_postmortem(skills_used=["broken-skill"])
        result = engine.on_run_completed(pm)
        assert result is not None

    def test_metrics_recorded_via_engine(self):
        cc = ChampionChallenger()
        vm = SkillVersionManager()
        vm.create_version("sk1", "prompt")
        vm.set_champion("sk1", "v1")

        engine = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=RegressionDetector(),
            champion_challenger=cc,
            version_manager=vm,
            comparison_interval=100,
        )
        pm = _make_postmortem(skills_used=["sk1"])
        engine.on_run_completed(pm)
        assert cc.get_run_count("sk1") >= 1
