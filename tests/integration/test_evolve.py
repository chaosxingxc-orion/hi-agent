"""Tests for the Evolve subsystem."""

from __future__ import annotations

import pytest
from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import RunRetrospective
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.regression_detector import RegressionDetector
from hi_agent.evolve.retrospective import PostmortemAnalyzer
from hi_agent.evolve.skill_extractor import SkillCandidate, SkillExtractor
from hi_agent.skill.evolver import SkillEvolver
from hi_agent.skill.observer import SkillMetrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_postmortem(
    *,
    run_id: str = "run-001",
    task_family: str = "code_review",
    outcome: str = "completed",
    stages_completed: list[str] | None = None,
    stages_failed: list[str] | None = None,
    branches_explored: int = 2,
    branches_pruned: int = 0,
    total_actions: int = 10,
    failure_codes: list[str] | None = None,
    duration_seconds: float = 120.0,
    quality_score: float | None = 0.8,
    efficiency_score: float | None = 0.7,
) -> RunRetrospective:
    """Create a RunRetrospective with sensible defaults."""
    return RunRetrospective(
        run_id=run_id,
        task_id="task-001",
        task_family=task_family,
        outcome=outcome,
        stages_completed=stages_completed or ["understand", "gather", "build"],
        stages_failed=stages_failed or [],
        branches_explored=branches_explored,
        branches_pruned=branches_pruned,
        total_actions=total_actions,
        failure_codes=failure_codes or [],
        duration_seconds=duration_seconds,
        quality_score=quality_score,
        efficiency_score=efficiency_score,
    )


class _FakeObserver:
    def __init__(self, metrics: SkillMetrics) -> None:
        self._metrics = metrics

    def get_metrics(self, skill_id: str) -> SkillMetrics:
        return self._metrics

    def get_all_metrics(self) -> dict[str, SkillMetrics]:
        return {self._metrics.skill_id: self._metrics}

    def get_observations(self, skill_id: str, limit: int = 100) -> list[object]:
        return []


class _FakeVersionManager:
    def get_champion(self, skill_id: str):
        return None


# ---------------------------------------------------------------------------
# PostmortemAnalyzer
# ---------------------------------------------------------------------------


class TestPostmortemAnalyzer:
    """Tests for PostmortemAnalyzer."""

    def test_successful_run_produces_result(self) -> None:
        """Analyze a successful run and get a valid EvolveResult."""
        analyzer = PostmortemAnalyzer()
        pm = _make_postmortem(outcome="completed")
        result = analyzer.analyze(pm)

        assert result.trigger == "per_run_retrospective"
        assert result.run_ids_analyzed == ["run-001"]
        assert result.metrics.runs_analyzed == 1
        assert result.timestamp  # non-empty

    def test_failed_run_with_many_failure_codes(self) -> None:
        """A run with many failure codes should produce routing heuristic changes."""
        analyzer = PostmortemAnalyzer()
        pm = _make_postmortem(
            outcome="failed",
            stages_failed=["build"],
            failure_codes=["missing_evidence", "invalid_context", "model_output_invalid"],
        )
        result = analyzer.analyze(pm)

        routing_changes = [c for c in result.changes if c.change_type == "routing_heuristic"]
        assert len(routing_changes) >= 1
        assert any("failure density" in c.description.lower() for c in routing_changes)

    def test_high_risk_failure_codes_detected(self) -> None:
        """High-risk failure codes should trigger specific routing changes."""
        analyzer = PostmortemAnalyzer()
        pm = _make_postmortem(
            outcome="failed",
            failure_codes=["exploration_budget_exhausted", "unsafe_action_blocked"],
        )
        result = analyzer.analyze(pm)

        high_risk_changes = [c for c in result.changes if "high-risk" in c.description.lower()]
        assert len(high_risk_changes) >= 1

    def test_legacy_budget_failure_code_detected(self) -> None:
        """Legacy budget_exhausted should still trigger the budget guard path."""
        analyzer = PostmortemAnalyzer()
        pm = _make_postmortem(
            outcome="failed",
            failure_codes=["budget_exhausted"],
        )
        result = analyzer.analyze(pm)

        high_risk_changes = [
            c
            for c in result.changes
            if c.change_type == "routing_heuristic" and "budget_exhausted" in c.target_id
        ]
        assert len(high_risk_changes) == 1

    def test_high_prune_ratio_detected(self) -> None:
        """High branch prune ratio should suggest tighter pre-filtering."""
        analyzer = PostmortemAnalyzer()
        pm = _make_postmortem(branches_explored=6, branches_pruned=5)
        result = analyzer.analyze(pm)

        branch_changes = [c for c in result.changes if "prune" in c.description.lower()]
        assert len(branch_changes) >= 1


# ---------------------------------------------------------------------------
# SkillExtractor
# ---------------------------------------------------------------------------


class TestSkillExtractor:
    """Tests for SkillExtractor."""

    def test_extracts_from_successful_run(self) -> None:
        """Successful runs with enough stages produce skill candidates."""
        extractor = SkillExtractor(min_confidence=0.5)
        pm = _make_postmortem(
            outcome="completed",
            stages_completed=["understand", "gather", "build"],
            quality_score=0.9,
        )
        candidates = extractor.extract(pm)

        assert len(candidates) >= 1
        assert all(isinstance(c, SkillCandidate) for c in candidates)
        assert all(c.lifecycle_stage == "candidate" for c in candidates)

    def test_ignores_failed_runs(self) -> None:
        """Failed runs should not produce any skill candidates."""
        extractor = SkillExtractor()
        pm = _make_postmortem(outcome="failed")
        candidates = extractor.extract(pm)

        assert candidates == []

    def test_ignores_aborted_runs(self) -> None:
        """Aborted runs should not produce any skill candidates."""
        extractor = SkillExtractor()
        pm = _make_postmortem(outcome="aborted")
        candidates = extractor.extract(pm)

        assert candidates == []

    def test_merge_candidates_deduplication(self) -> None:
        """Merging candidates with same skill_id increments evidence count."""
        extractor = SkillExtractor(min_confidence=0.5)

        pm1 = _make_postmortem(run_id="run-001", quality_score=0.8)
        pm2 = _make_postmortem(run_id="run-002", quality_score=0.85)

        c1 = extractor.extract(pm1)
        c2 = extractor.extract(pm2)

        assert len(c1) >= 1
        assert len(c2) >= 1

        merged = extractor.merge_candidates(c1, c2)

        # Same task_family + pattern -> same skill_id, so merged should deduplicate.
        skill_ids = [c.skill_id for c in merged]
        assert len(skill_ids) == len(set(skill_ids))

        # Evidence count should be > 1 for deduplicated entries.
        for c in merged:
            if c.skill_id == c1[0].skill_id:
                assert c.evidence_count >= 2

    def test_merge_candidates_preserves_unique(self) -> None:
        """Merging candidates with different skill_ids keeps both."""
        extractor = SkillExtractor(min_confidence=0.5)

        pm1 = _make_postmortem(run_id="run-001", task_family="code_review", quality_score=0.8)
        pm2 = _make_postmortem(run_id="run-002", task_family="data_analysis", quality_score=0.8)

        c1 = extractor.extract(pm1)
        c2 = extractor.extract(pm2)

        merged = extractor.merge_candidates(c1, c2)
        assert len(merged) >= 2


# ---------------------------------------------------------------------------
# SkillEvolver
# ---------------------------------------------------------------------------


class TestSkillEvolver:
    """Tests for budget-aware skill evolution heuristics."""

    @pytest.mark.parametrize(
        "failure_code",
        [
            "budget_exhausted",
            "exploration_budget_exhausted",
            "execution_budget_exhausted",
        ],
    )
    def test_budget_failure_codes_map_to_same_suggestion(self, failure_code: str) -> None:
        metrics = SkillMetrics(
            skill_id="skill_abc",
            total_executions=10,
            success_count=4,
            failure_count=6,
            success_rate=0.4,
            avg_quality=0.6,
            avg_tokens=0.0,
            avg_latency_ms=0.0,
            failure_patterns=[failure_code],
        )
        evolver = SkillEvolver(_FakeObserver(metrics), _FakeVersionManager())

        analysis = evolver.analyze_skill("skill_abc")

        assert any(
            "token-efficiency instructions" in suggestion for suggestion in analysis.suggestions
        )


# ---------------------------------------------------------------------------
# RegressionDetector
# ---------------------------------------------------------------------------


class TestRegressionDetector:
    """Tests for RegressionDetector."""

    def test_no_regression_on_stable_metrics(self) -> None:
        """Stable metrics should not flag a regression."""
        detector = RegressionDetector(baseline_window=5, threshold=0.15)
        for i in range(6):
            detector.record(f"run-{i}", "code_review", quality=0.8, efficiency=0.7)

        report = detector.check("code_review")
        assert not report.is_regression
        assert report.recommendation == "no_action"

    def test_detects_quality_regression(self) -> None:
        """A sudden quality drop should be flagged."""
        detector = RegressionDetector(baseline_window=5, threshold=0.15)
        for i in range(5):
            detector.record(f"run-{i}", "code_review", quality=0.8, efficiency=0.7)
        # Introduce a quality regression.
        detector.record("run-bad", "code_review", quality=0.5, efficiency=0.7)

        report = detector.check("code_review")
        assert report.is_regression
        assert report.quality_delta < -0.15
        assert report.recommendation in ("investigate", "rollback")

    def test_detects_dual_regression_as_rollback(self) -> None:
        """Both quality and efficiency dropping should recommend rollback."""
        detector = RegressionDetector(baseline_window=5, threshold=0.15)
        for i in range(5):
            detector.record(f"run-{i}", "code_review", quality=0.8, efficiency=0.8)
        detector.record("run-bad", "code_review", quality=0.5, efficiency=0.5)

        report = detector.check("code_review")
        assert report.is_regression
        assert report.recommendation == "rollback"

    def test_insufficient_data(self) -> None:
        """With only one run, no regression should be reported."""
        detector = RegressionDetector()
        detector.record("run-0", "code_review", quality=0.5, efficiency=0.5)

        report = detector.check("code_review")
        assert not report.is_regression
        assert report.recommendation == "no_action"


# ---------------------------------------------------------------------------
# ChampionChallenger
# ---------------------------------------------------------------------------


class TestChampionChallenger:
    """Tests for ChampionChallenger."""

    def test_challenger_wins(self) -> None:
        """A better challenger should be recommended for promotion."""
        cc = ChampionChallenger()
        cc.register_champion("routing_v1", "v1", {"quality": 0.7, "efficiency": 0.6})
        cc.register_challenger("routing_v1", "v2", {"quality": 0.9, "efficiency": 0.8})

        result = cc.compare("routing_v1")
        assert result.winner == "challenger"
        assert result.recommendation == "promote_challenger"
        assert result.challenger_score > result.champion_score

    def test_champion_wins(self) -> None:
        """A weaker challenger should keep the champion."""
        cc = ChampionChallenger()
        cc.register_champion("routing_v1", "v1", {"quality": 0.9, "efficiency": 0.8})
        cc.register_challenger("routing_v1", "v2", {"quality": 0.5, "efficiency": 0.4})

        result = cc.compare("routing_v1")
        assert result.winner == "champion"
        assert result.recommendation == "keep_champion"

    def test_missing_challenger_is_inconclusive(self) -> None:
        """Missing challenger should return inconclusive."""
        cc = ChampionChallenger()
        cc.register_champion("routing_v1", "v1", {"quality": 0.8})

        result = cc.compare("routing_v1")
        assert result.winner == "inconclusive"
        assert result.recommendation == "need_more_data"

    def test_equal_scores_inconclusive(self) -> None:
        """Equal scores should return inconclusive."""
        cc = ChampionChallenger()
        cc.register_champion("routing_v1", "v1", {"quality": 0.8})
        cc.register_challenger("routing_v1", "v2", {"quality": 0.8})

        result = cc.compare("routing_v1")
        assert result.winner == "inconclusive"
        assert result.recommendation == "need_more_data"


# ---------------------------------------------------------------------------
# EvolveEngine
# ---------------------------------------------------------------------------


class TestEvolveEngine:
    """Tests for EvolveEngine."""

    def test_on_run_completed_end_to_end(self) -> None:
        """End-to-end test: on_run_completed produces a valid EvolveResult."""
        engine = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=RegressionDetector(),
            champion_challenger=ChampionChallenger(),
        )
        pm = _make_postmortem(
            outcome="completed",
            stages_completed=["understand", "gather", "build"],
            quality_score=0.85,
            efficiency_score=0.75,
        )

        result = engine.on_run_completed(pm)

        assert result.trigger == "per_run_retrospective"
        assert result.run_ids_analyzed == ["run-001"]
        assert result.metrics.runs_analyzed == 1
        assert isinstance(result.changes, list)

    def test_on_run_completed_extracts_skills(self) -> None:
        """Successful runs should produce skill candidate changes."""
        engine = EvolveEngine(
            skill_extractor=SkillExtractor(min_confidence=0.5),
            regression_detector=RegressionDetector(),
            champion_challenger=ChampionChallenger(),
        )
        pm = _make_postmortem(
            outcome="completed",
            stages_completed=["understand", "gather", "build"],
            quality_score=0.9,
        )

        result = engine.on_run_completed(pm)

        skill_changes = [c for c in result.changes if c.change_type == "skill_candidate"]
        assert len(skill_changes) >= 1
        assert result.metrics.skill_candidates_found >= 1

    def test_on_run_completed_records_regression_data(self) -> None:
        """After enough runs, regression detection should work."""
        detector = RegressionDetector(baseline_window=3, threshold=0.15)
        engine = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=detector,
            champion_challenger=ChampionChallenger(),
        )

        # Record 4 good runs.
        for i in range(4):
            pm = _make_postmortem(
                run_id=f"run-{i}",
                quality_score=0.8,
                efficiency_score=0.8,
            )
            engine.on_run_completed(pm)

        # Now a bad run.
        bad_pm = _make_postmortem(
            run_id="run-bad",
            quality_score=0.4,
            efficiency_score=0.4,
        )
        engine.on_run_completed(bad_pm)

        report = engine.check_regression("code_review")
        assert report.is_regression

    def test_batch_evolve_scope_isolation(self) -> None:
        """Batch evolve should only return changes matching the requested scope."""
        engine = EvolveEngine(
            skill_extractor=SkillExtractor(min_confidence=0.5),
            regression_detector=RegressionDetector(),
            champion_challenger=ChampionChallenger(),
        )

        postmortems = [
            _make_postmortem(
                run_id=f"run-{i}",
                outcome="completed",
                stages_completed=["understand", "gather", "build"],
                quality_score=0.9,
                failure_codes=["missing_evidence", "invalid_context", "model_output_invalid"],
                branches_explored=6,
                branches_pruned=5,
            )
            for i in range(3)
        ]

        # Request only skill_candidates_only scope.
        result = engine.batch_evolve(postmortems, change_scope="skill_candidates_only")

        assert result.trigger == "batch_evolution"
        assert result.change_scope == "skill_candidates_only"
        # All changes should be skill_candidate type only.
        for change in result.changes:
            assert change.change_type == "skill_candidate", (
                f"Expected skill_candidate but got {change.change_type}"
            )

    def test_change_scope_isolation_routing_only(self) -> None:
        """Batch evolve with routing_only scope excludes skill candidates."""
        engine = EvolveEngine(
            skill_extractor=SkillExtractor(min_confidence=0.5),
            regression_detector=RegressionDetector(),
            champion_challenger=ChampionChallenger(),
        )

        postmortems = [
            _make_postmortem(
                run_id=f"run-{i}",
                outcome="completed",
                stages_completed=["understand", "gather", "build"],
                quality_score=0.9,
                failure_codes=["missing_evidence", "invalid_context", "model_output_invalid"],
                branches_explored=6,
                branches_pruned=5,
            )
            for i in range(3)
        ]

        result = engine.batch_evolve(postmortems, change_scope="routing_only")

        assert result.change_scope == "routing_only"
        for change in result.changes:
            assert change.change_type == "routing_heuristic", (
                f"Expected routing_heuristic but got {change.change_type}"
            )
