"""Tests for the skill evolution pipeline: observer, version, evolver."""

from __future__ import annotations

import json
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from hi_agent.skill.definition import SkillDefinition
from hi_agent.skill.evolver import (
    EvolutionReport,
    SkillEvolver,
    SkillPattern,
)
from hi_agent.skill.observer import (
    SkillMetrics,
    SkillObservation,
    SkillObserver,
    make_observation_id,
)
from hi_agent.skill.version import SkillVersionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_obs(
    skill_id: str = "skill_abc",
    version: str = "v1",
    run_id: str = "run-1",
    stage_id: str = "S1",
    success: bool = True,
    quality_score: float | None = 0.8,
    tokens_used: int = 100,
    latency_ms: int = 50,
    failure_code: str | None = None,
    task_family: str = "analysis",
    tags: list[str] | None = None,
    input_summary: str = "input",
    output_summary: str = "output",
) -> SkillObservation:
    return SkillObservation(
        observation_id=make_observation_id(),
        skill_id=skill_id,
        skill_version=version,
        run_id=run_id,
        stage_id=stage_id,
        timestamp="2026-04-07T00:00:00+00:00",
        success=success,
        input_summary=input_summary,
        output_summary=output_summary,
        quality_score=quality_score,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        failure_code=failure_code,
        task_family=task_family,
        tags=tags or [],
    )


# ===================================================================
# Observer Tests
# ===================================================================


class TestSkillObserver:
    """Tests for SkillObserver."""

    def test_observe_writes_jsonl(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        obs = _make_obs()
        observer.observe(obs)

        path = tmp_path / f"{obs.skill_id}.jsonl"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["skill_id"] == obs.skill_id
        assert data["success"] is True

    def test_get_observations_loads_from_disk(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        for i in range(5):
            observer.observe(_make_obs(run_id=f"run-{i}"))

        loaded = observer.get_observations("skill_abc")
        assert len(loaded) == 5
        assert loaded[0].skill_id == "skill_abc"

    def test_get_observations_respects_limit(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        for i in range(10):
            observer.observe(_make_obs(run_id=f"run-{i}"))

        loaded = observer.get_observations("skill_abc", limit=3)
        assert len(loaded) == 3
        # Should be the last 3
        assert loaded[0].run_id == "run-7"

    def test_get_metrics_aggregates(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        # 7 successes, 3 failures
        for i in range(7):
            observer.observe(_make_obs(run_id=f"run-{i}", quality_score=0.9))
        for i in range(3):
            observer.observe(
                _make_obs(
                    run_id=f"fail-{i}",
                    success=False,
                    quality_score=0.3,
                    failure_code="missing_evidence",
                )
            )

        metrics = observer.get_metrics("skill_abc")
        assert metrics.total_executions == 10
        assert metrics.success_count == 7
        assert metrics.failure_count == 3
        assert metrics.success_rate == pytest.approx(0.7)
        # avg quality = (7*0.9 + 3*0.3) / 10 = 7.2/10 = 0.72
        assert metrics.avg_quality == pytest.approx(0.72, abs=0.01)
        assert "missing_evidence" in metrics.failure_patterns

    def test_thread_safety(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        errors: list[Exception] = []

        def _write(tid: int) -> None:
            try:
                for i in range(20):
                    observer.observe(_make_obs(run_id=f"t{tid}-r{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        loaded = observer.get_observations("skill_abc", limit=10000)
        assert len(loaded) == 100  # 5 threads * 20 each

    def test_observation_truncation(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        long_input = "x" * 1000
        long_output = "y" * 1000
        obs = _make_obs(input_summary=long_input, output_summary=long_output)
        assert len(obs.input_summary) == 500
        assert len(obs.output_summary) == 500

        observer.observe(obs)
        loaded = observer.get_observations("skill_abc")
        assert len(loaded[0].input_summary) == 500
        assert len(loaded[0].output_summary) == 500

    def test_get_observations_empty(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        loaded = observer.get_observations("nonexistent")
        assert loaded == []

    def test_get_all_metrics(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        observer.observe(_make_obs(skill_id="skill_a"))
        observer.observe(_make_obs(skill_id="skill_b"))

        all_m = observer.get_all_metrics()
        assert "skill_a" in all_m
        assert "skill_b" in all_m

    def test_get_metrics_version_stats(self, tmp_path: Any) -> None:
        observer = SkillObserver(storage_dir=str(tmp_path))
        observer.observe(_make_obs(version="v1"))
        observer.observe(_make_obs(version="v1", success=False))
        observer.observe(_make_obs(version="v2"))

        metrics = observer.get_metrics("skill_abc")
        assert "v1" in metrics.version_stats
        assert "v2" in metrics.version_stats
        assert metrics.version_stats["v1"]["total"] == 2
        assert metrics.version_stats["v2"]["total"] == 1


# ===================================================================
# Version Tests
# ===================================================================


class TestSkillVersionManager:
    """Tests for SkillVersionManager."""

    def test_create_version_auto_increments(self) -> None:
        mgr = SkillVersionManager()
        v1 = mgr.create_version("sk1", "prompt v1")
        v2 = mgr.create_version("sk1", "prompt v2")
        v3 = mgr.create_version("sk1", "prompt v3")
        assert v1.version == "v1"
        assert v2.version == "v2"
        assert v3.version == "v3"

    def test_first_version_is_champion(self) -> None:
        mgr = SkillVersionManager()
        v1 = mgr.create_version("sk1", "prompt")
        assert v1.is_champion is True

    def test_set_get_champion(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "prompt v1")
        mgr.create_version("sk1", "prompt v2")
        mgr.set_champion("sk1", "v2")
        champ = mgr.get_champion("sk1")
        assert champ is not None, "Expected non-None result for champ"
        assert champ.version == "v2"
        # v1 should no longer be champion
        versions = mgr.list_versions("sk1")
        assert not versions[0].is_champion

    def test_set_get_challenger(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "prompt v1")
        mgr.create_version("sk1", "prompt v2")
        mgr.set_challenger("sk1", "v2")
        chall = mgr.get_challenger("sk1")
        assert chall is not None, "Expected non-None result for chall"
        assert chall.version == "v2"

    def test_select_version_respects_traffic_split(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "champion prompt")
        mgr.create_version("sk1", "challenger prompt")
        mgr.set_challenger("sk1", "v2")

        champion_count = 0
        challenger_count = 0
        n = 1000
        for _ in range(n):
            selected = mgr.select_version("sk1", traffic_split=0.3)
            if selected.version == "v1":
                champion_count += 1
            else:
                challenger_count += 1

        # With 30% traffic to challenger, expect roughly 300 +/- margin
        assert challenger_count > 200, f"Too few challenger selections: {challenger_count}"
        assert challenger_count < 400, f"Too many challenger selections: {challenger_count}"
        assert champion_count + challenger_count == n

    def test_select_version_no_challenger(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "champion prompt")
        selected = mgr.select_version("sk1", traffic_split=0.5)
        assert selected.version == "v1"

    def test_promote_challenger(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "champion prompt")
        v2 = mgr.create_version("sk1", "challenger prompt")
        mgr.set_challenger("sk1", "v2")

        # Give challenger better metrics
        v2.metrics = SkillMetrics(skill_id="sk1", success_rate=0.9)
        champ = mgr.get_champion("sk1")
        assert champ is not None, "Expected non-None result for champ"
        champ.metrics = SkillMetrics(skill_id="sk1", success_rate=0.6)

        result = mgr.promote_challenger("sk1")
        assert result is True
        new_champ = mgr.get_champion("sk1")
        assert new_champ is not None, "Expected non-None result for new_champ"
        assert new_champ.version == "v2"
        # Challenger flag should be cleared
        assert new_champ.is_challenger is False

    def test_promote_challenger_no_challenger(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "prompt")
        assert mgr.promote_challenger("sk1") is False

    def test_rollback(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "prompt v1")
        mgr.create_version("sk1", "prompt v2")
        mgr.set_champion("sk1", "v2")

        result = mgr.rollback("sk1")
        assert result is True
        champ = mgr.get_champion("sk1")
        assert champ is not None, "Expected non-None result for champ"
        assert champ.version == "v1"

    def test_rollback_single_version(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "prompt v1")
        assert mgr.rollback("sk1") is False

    def test_compare_returns_metric_differences(self) -> None:
        mgr = SkillVersionManager()
        v1 = mgr.create_version("sk1", "champion")
        v2 = mgr.create_version("sk1", "challenger")
        mgr.set_challenger("sk1", "v2")

        v1.metrics = SkillMetrics(
            skill_id="sk1", success_rate=0.7, avg_quality=0.8, avg_latency_ms=100
        )
        v2.metrics = SkillMetrics(
            skill_id="sk1", success_rate=0.85, avg_quality=0.9, avg_latency_ms=80
        )

        comparison = mgr.compare("sk1")
        assert comparison["champion_version"] == "v1"
        assert comparison["challenger_version"] == "v2"
        assert comparison["recommendation"] == "promote_challenger"

    def test_compare_no_data(self) -> None:
        mgr = SkillVersionManager()
        comparison = mgr.compare("nonexistent")
        assert comparison["recommendation"] == "no_data"

    def test_save_load_persistence(self, tmp_path: Any) -> None:
        mgr = SkillVersionManager(storage_dir=str(tmp_path))
        mgr.create_version("sk1", "prompt v1", {"temperature": 0.5})
        mgr.create_version("sk1", "prompt v2")
        mgr.set_challenger("sk1", "v2")

        mgr.save()

        mgr2 = SkillVersionManager(storage_dir=str(tmp_path))
        mgr2.load()

        versions = mgr2.list_versions("sk1")
        assert len(versions) == 2
        assert versions[0].version == "v1"
        assert versions[0].is_champion is True
        assert versions[1].version == "v2"
        assert versions[1].is_challenger is True
        assert versions[0].parameters == {"temperature": 0.5}

    def test_list_versions(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "p1")
        mgr.create_version("sk1", "p2")
        mgr.create_version("sk2", "p1")

        assert len(mgr.list_versions("sk1")) == 2
        assert len(mgr.list_versions("sk2")) == 1
        assert len(mgr.list_versions("sk3")) == 0

    def test_select_version_no_versions_raises(self) -> None:
        mgr = SkillVersionManager()
        with pytest.raises(KeyError):
            mgr.select_version("nonexistent")

    def test_set_champion_invalid_version_raises(self) -> None:
        mgr = SkillVersionManager()
        mgr.create_version("sk1", "prompt")
        with pytest.raises(KeyError):
            mgr.set_champion("sk1", "v99")


# ===================================================================
# Evolver Tests
# ===================================================================


class TestSkillEvolver:
    """Tests for SkillEvolver."""

    def _setup(self, tmp_path: Any) -> tuple[SkillObserver, SkillVersionManager, SkillEvolver]:
        observer = SkillObserver(storage_dir=str(tmp_path / "obs"))
        version_mgr = SkillVersionManager(storage_dir=str(tmp_path / "ver"))
        evolver = SkillEvolver(observer, version_mgr)
        return observer, version_mgr, evolver

    def test_analyze_skill_identifies_underperforming(self, tmp_path: Any) -> None:
        observer, _, evolver = self._setup(tmp_path)

        # 3 successes, 7 failures => 30% success rate
        for i in range(3):
            observer.observe(_make_obs(run_id=f"s-{i}"))
        for i in range(7):
            observer.observe(
                _make_obs(
                    run_id=f"f-{i}",
                    success=False,
                    failure_code="missing_evidence",
                )
            )

        analysis = evolver.analyze_skill("skill_abc")
        assert analysis.success_rate == pytest.approx(0.3)
        assert analysis.optimization_needed is True
        assert len(analysis.top_failures) > 0

    def test_analyze_skill_healthy(self, tmp_path: Any) -> None:
        observer, _, evolver = self._setup(tmp_path)
        for i in range(10):
            observer.observe(_make_obs(run_id=f"s-{i}"))

        analysis = evolver.analyze_skill("skill_abc")
        assert analysis.success_rate == 1.0
        assert analysis.optimization_needed is False

    def test_optimize_prompt_without_llm(self, tmp_path: Any) -> None:
        observer, version_mgr, evolver = self._setup(tmp_path)
        version_mgr.create_version("skill_abc", "Original prompt")

        for i in range(7):
            observer.observe(
                _make_obs(
                    run_id=f"f-{i}",
                    success=False,
                    failure_code="missing_evidence",
                )
            )
        for i in range(3):
            observer.observe(_make_obs(run_id=f"s-{i}"))

        result = evolver.optimize_prompt("skill_abc")
        assert result is not None, "Expected non-None result for result"
        assert "Original prompt" in result
        assert "Improvement Notes" in result

    def test_optimize_prompt_not_needed(self, tmp_path: Any) -> None:
        observer, _, evolver = self._setup(tmp_path)
        for i in range(10):
            observer.observe(_make_obs(run_id=f"s-{i}"))

        result = evolver.optimize_prompt("skill_abc")
        assert result is None

    def test_optimize_prompt_with_mock_llm(self, tmp_path: Any) -> None:
        observer, version_mgr, _ = self._setup(tmp_path)

        # Create mock LLM
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Improved prompt from LLM"
        mock_llm.complete.return_value = mock_response

        evolver = SkillEvolver(observer, version_mgr, llm_gateway=mock_llm)
        version_mgr.create_version("skill_abc", "Original prompt")

        for i in range(8):
            observer.observe(_make_obs(run_id=f"f-{i}", success=False, failure_code="no_progress"))
        for i in range(2):
            observer.observe(_make_obs(run_id=f"s-{i}"))

        result = evolver.optimize_prompt("skill_abc")
        assert result == "Improved prompt from LLM"
        mock_llm.complete.assert_called_once()

    def test_deploy_optimization(self, tmp_path: Any) -> None:
        _, version_mgr, evolver = self._setup(tmp_path)
        version_mgr.create_version("skill_abc", "Original")

        record = evolver.deploy_optimization("skill_abc", "Improved prompt")
        assert record.prompt_content == "Improved prompt"
        assert record.is_challenger is True

        challenger = version_mgr.get_challenger("skill_abc")
        assert challenger is not None, "Expected non-None result for challenger"
        assert challenger.version == record.version

    def test_discover_patterns(self, tmp_path: Any) -> None:
        observer, _, evolver = self._setup(tmp_path)

        # Create observations with a recurring pattern
        for i in range(5):
            observer.observe(
                _make_obs(
                    run_id=f"run-{i}",
                    task_family="data_analysis",
                    stage_id="S2",
                    tags=["search", "filter", "aggregate"],
                )
            )

        patterns = evolver.discover_patterns(min_occurrences=3)
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.occurrences >= 3
        assert "data_analysis" in p.task_families

    def test_discover_patterns_empty(self, tmp_path: Any) -> None:
        _, _, evolver = self._setup(tmp_path)
        patterns = evolver.discover_patterns()
        assert patterns == []

    def test_create_skill_from_pattern(self, tmp_path: Any) -> None:
        _, _, evolver = self._setup(tmp_path)

        pattern = SkillPattern(
            pattern_id="pat_test123456",
            description="Recurring data cleanup pattern",
            occurrences=5,
            task_families=["etl"],
            stages=["S2", "S3"],
            tool_sequence=["validate", "transform", "load"],
            confidence=0.8,
            source_sessions=["run-1", "run-2"],
        )

        skill_def = evolver.create_skill_from_pattern(pattern)
        assert skill_def is not None, "Expected non-None result for skill_def"
        assert isinstance(skill_def, SkillDefinition)
        assert skill_def.source == "evolved"
        assert "etl" in skill_def.when_to_use
        assert skill_def.confidence == 0.8

    def test_create_skill_with_mock_llm(self, tmp_path: Any) -> None:
        observer, version_mgr, _ = self._setup(tmp_path)

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "LLM-generated skill prompt"
        mock_llm.complete.return_value = mock_response

        evolver = SkillEvolver(observer, version_mgr, llm_gateway=mock_llm)

        pattern = SkillPattern(
            pattern_id="pat_llmtest1234",
            description="Pattern for LLM test",
            occurrences=5,
            task_families=["coding"],
            stages=["S1"],
            tool_sequence=["read", "edit"],
            confidence=0.9,
            source_sessions=["r1"],
        )

        skill_def = evolver.create_skill_from_pattern(pattern)
        assert skill_def is not None, "Expected non-None result for skill_def"
        assert skill_def.prompt_content == "LLM-generated skill prompt"

    def test_evolve_cycle(self, tmp_path: Any) -> None:
        observer, version_mgr, evolver = self._setup(tmp_path)

        # Create a skill with poor performance
        version_mgr.create_version("skill_abc", "Bad prompt")

        # 3 successes, 12 failures (min_observations=10, success_rate < 0.7)
        for i in range(3):
            observer.observe(_make_obs(run_id=f"s-{i}"))
        for i in range(12):
            observer.observe(
                _make_obs(
                    run_id=f"f-{i}",
                    success=False,
                    failure_code="invalid_context",
                )
            )

        report = evolver.evolve_cycle(min_observations=10)
        assert isinstance(report, EvolutionReport)
        assert report.skills_analyzed >= 1
        assert report.skills_optimized >= 1
        assert report.challenger_deployed >= 1

    def test_evolve_cycle_skips_low_observation_skills(self, tmp_path: Any) -> None:
        observer, _, evolver = self._setup(tmp_path)

        # Only 3 observations — below min_observations=10
        for i in range(3):
            observer.observe(_make_obs(run_id=f"s-{i}"))

        report = evolver.evolve_cycle(min_observations=10)
        assert report.skills_analyzed == 0
        assert report.skills_optimized == 0

    def test_evolution_report_counts(self, tmp_path: Any) -> None:
        report = EvolutionReport(
            skills_analyzed=5,
            skills_optimized=2,
            patterns_discovered=3,
            skills_created=1,
            challenger_deployed=2,
            details=["detail 1", "detail 2"],
        )
        assert report.skills_analyzed == 5
        assert report.skills_optimized == 2
        assert report.patterns_discovered == 3
        assert report.skills_created == 1
        assert report.challenger_deployed == 2
        assert len(report.details) == 2
