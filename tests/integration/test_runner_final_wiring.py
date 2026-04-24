"""Tests for final wiring: FailureCollector, Watchdog, EpisodeBuilder, SkillRecorder.

Validates that RunExecutor correctly integrates:
- FailureCollector receives structured FailureRecord on action failures
- ProgressWatchdog triggers Gate B on repeated failures
- EpisodeBuilder + EpisodicMemoryStore auto-stores episode after run
- SkillUsageRecorder records skill usage when proposal has skill_id
- Backward compatibility: all new params None -> same behavior
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import Any, ClassVar

from hi_agent.contracts import TaskContract
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.taxonomy import FailureCode, FailureRecord
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.runner import RunExecutor
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import ManagedSkill, SkillRegistry

from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_contract(
    task_id: str = "wiring-test-001",
    goal: str = "final wiring test",
    **kwargs: object,
) -> TaskContract:
    return TaskContract(task_id=task_id, goal=goal, **kwargs)


# ---------------------------------------------------------------------------
# Route engine helpers
# ---------------------------------------------------------------------------


@dataclass
class _Proposal:
    action_kind: str
    branch_id: str
    rationale: str = "test"
    skill_id: str = ""


class _FailingRouteEngine:
    """Route engine that proposes actions which always fail."""

    def __init__(self, num_proposals: int = 1) -> None:
        self._num = num_proposals

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[_Proposal]:
        return [
            _Proposal(
                action_kind="fail_action",
                branch_id=f"b-fail-{i}",
            )
            for i in range(self._num)
        ]


class _SuccessRouteEngine:
    """Route engine that proposes a single succeeding action per stage."""

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[_Proposal]:
        return [
            _Proposal(action_kind="gather_data", branch_id="b-ok-0"),
        ]


class _SkillRouteEngine:
    """Route engine that proposes actions with skill_id metadata.

    Uses the same action mapping as RuleRouteEngine so actions succeed.
    """

    STAGE_ACTIONS: ClassVar[dict[str, str]] = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    def __init__(self, skill_id: str = "skill-abc") -> None:
        self._skill_id = skill_id

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[_Proposal]:
        action = self.STAGE_ACTIONS.get(stage_id, "analyze_goal")
        return [
            _Proposal(
                action_kind=action,
                branch_id=f"b-sk-{stage_id}",
                skill_id=self._skill_id,
            ),
        ]


class _ManyFailRouteEngine:
    """Route engine producing many failing proposals to trigger watchdog."""

    def __init__(self, count: int = 6) -> None:
        self._count = count

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[_Proposal]:
        return [
            _Proposal(
                action_kind="fail_action",
                branch_id=f"b-mf-{i}",
            )
            for i in range(self._count)
        ]


# ---------------------------------------------------------------------------
# 1. FailureCollector receives failure records during run
# ---------------------------------------------------------------------------


def test_failure_collector_receives_records_on_action_failure():
    """When actions fail, FailureCollector should receive FailureRecords."""
    contract = _make_contract(constraints=["fail_action:fail_action"])
    kernel = MockKernel()
    collector = FailureCollector()

    runner = RunExecutor(
        contract,
        kernel,
        route_engine=_FailingRouteEngine(num_proposals=2),
        failure_collector=collector,
     raw_memory=RawMemoryStore())
    runner.execute()

    records = collector.get_all()
    assert len(records) > 0, "Collector should have at least one record"
    for rec in records:
        assert isinstance(rec, FailureRecord)
        assert isinstance(rec.failure_code, FailureCode)
        assert rec.run_id != ""
        assert rec.stage_id != ""


def test_failure_collector_summary_included_in_postmortem():
    """Postmortem failure_codes should come from FailureCollector when available."""
    contract = _make_contract(constraints=["fail_action:fail_action"])
    kernel = MockKernel()
    collector = FailureCollector()

    # Use a fake evolve engine to capture the postmortem
    class _CaptureEvolve:
        def __init__(self) -> None:
            self.postmortems: list[Any] = []

        def on_run_completed(self, pm: Any) -> None:
            self.postmortems.append(pm)

    evolve = _CaptureEvolve()
    runner = RunExecutor(
        contract,
        kernel,
        route_engine=_FailingRouteEngine(num_proposals=1),
        failure_collector=collector,
        evolve_engine=evolve,
     raw_memory=RawMemoryStore())
    runner.execute()

    # Postmortem should have failure codes from the collector
    assert len(evolve.postmortems) == 1
    pm = evolve.postmortems[0]
    assert len(pm.failure_codes) > 0
    # Verify collector codes match postmortem codes
    collector_codes = collector.get_failure_codes()
    assert pm.failure_codes == collector_codes


# ---------------------------------------------------------------------------
# 2. ProgressWatchdog triggers on repeated failures
# ---------------------------------------------------------------------------


def test_watchdog_triggers_gate_b_on_repeated_failures():
    """When consecutive failures exceed threshold, watchdog should trigger Gate B."""
    contract = _make_contract(constraints=["fail_action:fail_action"])
    kernel = MockKernel()
    collector = FailureCollector()
    watchdog = ProgressWatchdog(max_consecutive_failures=3)

    runner = RunExecutor(
        contract,
        kernel,
        route_engine=_ManyFailRouteEngine(count=5),
        failure_collector=collector,
        watchdog=watchdog,
     raw_memory=RawMemoryStore())
    runner.execute()

    # Watchdog should have detected no-progress
    no_progress_records = collector.get_by_code(FailureCode.NO_PROGRESS)
    assert len(no_progress_records) > 0, "Watchdog should have recorded NO_PROGRESS failures"

    # Gate B (route_direction) should have been opened
    gate_b_requests = [g for g in kernel.gates.values() if g["gate_type"] == "route_direction"]
    assert len(gate_b_requests) > 0, "Gate B should be triggered by watchdog"


def test_watchdog_reset_at_stage_transition():
    """Watchdog should be reset when transitioning between stages."""
    contract = _make_contract()
    kernel = MockKernel()
    watchdog = ProgressWatchdog(max_consecutive_failures=100)

    runner = RunExecutor(
        contract,
        kernel,
        watchdog=watchdog,
     raw_memory=RawMemoryStore())
    runner.execute()

    # After completion, watchdog should have been reset at each stage
    # (consecutive failures should be 0 since all actions succeed and
    # reset happens at each stage start)
    assert watchdog.consecutive_failures == 0


# ---------------------------------------------------------------------------
# 3. EpisodeBuilder + EpisodicStore auto-stores episode after run
# ---------------------------------------------------------------------------


def test_episode_stored_after_successful_run():
    """After completed run, episode should be built and stored."""
    contract = _make_contract()
    kernel = MockKernel()

    with tempfile.TemporaryDirectory() as tmpdir:
        episode_builder = EpisodeBuilder()
        episodic_store = EpisodicMemoryStore(storage_dir=tmpdir)

        runner = RunExecutor(
            contract,
            kernel,
            episode_builder=episode_builder,
            episodic_store=episodic_store,
         raw_memory=RawMemoryStore())
        result = runner.execute()
        assert result == "completed"

        # Episode should be stored
        assert episodic_store.count() == 1
        episode = episodic_store.get(runner.run_id)
        assert episode is not None
        assert episode.task_id == contract.task_id
        assert episode.outcome == "completed"
        assert episode.goal == contract.goal


def test_episode_stored_after_failed_run():
    """After failed run, episode should still be built and stored."""
    contract = _make_contract(constraints=["fail_action:fail_action"])
    kernel = MockKernel()

    with tempfile.TemporaryDirectory() as tmpdir:
        episode_builder = EpisodeBuilder()
        episodic_store = EpisodicMemoryStore(storage_dir=tmpdir)

        runner = RunExecutor(
            contract,
            kernel,
            route_engine=_FailingRouteEngine(num_proposals=1),
            episode_builder=episode_builder,
            episodic_store=episodic_store,
         raw_memory=RawMemoryStore())
        result = runner.execute()
        assert result == "failed"

        assert episodic_store.count() == 1
        episode = episodic_store.get(runner.run_id)
        assert episode is not None
        assert episode.outcome == "failed"


def test_no_episode_when_builder_is_none():
    """When episode_builder is None, no episode should be stored."""
    contract = _make_contract()
    kernel = MockKernel()

    with tempfile.TemporaryDirectory() as tmpdir:
        episodic_store = EpisodicMemoryStore(storage_dir=tmpdir)

        runner = RunExecutor(
            contract,
            kernel,
            episode_builder=None,
            episodic_store=episodic_store,
         raw_memory=RawMemoryStore())
        runner.execute()

        assert episodic_store.count() == 0


# ---------------------------------------------------------------------------
# 4. SkillRecorder records usage
# ---------------------------------------------------------------------------


def test_skill_recorder_records_usage():
    """When proposal has skill_id, SkillUsageRecorder should record it."""
    contract = _make_contract()
    kernel = MockKernel()

    registry = SkillRegistry()
    skill = ManagedSkill(
        skill_id="skill-abc",
        name="Test Skill",
        description="A test skill",
    )
    registry._skills["skill-abc"] = skill

    recorder = SkillUsageRecorder(registry=registry)

    runner = RunExecutor(
        contract,
        kernel,
        route_engine=_SkillRouteEngine(skill_id="skill-abc"),
        skill_recorder=recorder,
     raw_memory=RawMemoryStore())
    result = runner.execute()
    assert result == "completed"

    # Skill should have been recorded
    run_skills = recorder.get_run_skills(runner.run_id)
    assert "skill-abc" in run_skills

    # Stats should reflect usage
    stats = recorder.get_usage_stats("skill-abc")
    assert stats["evidence_count"] > 0


def test_skill_recorder_not_called_without_skill_id():
    """When proposals lack skill_id, recorder should have no entries."""
    contract = _make_contract()
    kernel = MockKernel()

    registry = SkillRegistry()
    recorder = SkillUsageRecorder(registry=registry)

    runner = RunExecutor(
        contract,
        kernel,
        skill_recorder=recorder,
     raw_memory=RawMemoryStore())
    runner.execute()

    run_skills = recorder.get_run_skills(runner.run_id)
    assert len(run_skills) == 0


# ---------------------------------------------------------------------------
# 5. Backward compatibility: all None -> same behavior
# ---------------------------------------------------------------------------


def test_backward_compat_all_none():
    """RunExecutor should work identically when all new params are defaults."""
    contract = _make_contract()
    kernel = MockKernel()

    runner = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
    result = runner.execute()
    assert result == "completed"


def test_backward_compat_explicit_none():
    """Explicitly passing None for all new params should work."""
    contract = _make_contract()
    kernel = MockKernel()

    runner = RunExecutor(
        contract,
        kernel,
        failure_collector=None,
        watchdog=None,
        episode_builder=None,
        episodic_store=None,
        skill_recorder=None,
     raw_memory=RawMemoryStore())
    result = runner.execute()
    assert result == "completed"


def test_default_failure_collector_created():
    """RunExecutor should create a default FailureCollector when None is passed."""
    contract = _make_contract()
    kernel = MockKernel()

    runner = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
    assert runner.failure_collector is not None
    assert isinstance(runner.failure_collector, FailureCollector)


def test_default_watchdog_created():
    """RunExecutor should create a default ProgressWatchdog when None is passed."""
    contract = _make_contract()
    kernel = MockKernel()

    runner = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
    assert runner.watchdog is not None
    assert isinstance(runner.watchdog, ProgressWatchdog)
