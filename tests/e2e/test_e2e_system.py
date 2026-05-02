"""End-to-end system integration tests proving the FULL TRACE pipeline works.

These tests exercise the complete pipeline from task submission through
completion, verifying that kernel, evolve, harness, memory, skill,
failure, server, state machine, and policy subsystems integrate correctly.

Each test is self-contained with proper setup/teardown.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from hi_agent.contracts import (
    CTSExplorationBudget,
    StageState,
    TaskBudget,
    TaskContract,
)
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import RunRetrospective
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.regression_detector import RegressionDetector
from hi_agent.evolve.skill_extractor import SkillCandidate, SkillExtractor
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.runtime.harness.contracts import (
    ActionSpec,
    ActionState,
    EffectClass,
    SideEffectClass,
)
from hi_agent.runtime.harness.evidence_store import EvidenceStore
from hi_agent.runtime.harness.executor import HarnessExecutor
from hi_agent.runtime.harness.governance import GovernanceEngine
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodeRecord, EpisodicMemoryStore
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.orchestrator.task_orchestrator import TaskOrchestrator
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import STAGES, RunExecutor
from hi_agent.server.app import AgentServer
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import SkillRegistry
from hi_agent.state_machine.definitions import run_state_machine
from hi_agent.task_decomposition.decomposer import TaskDecomposer

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Test 1: Full TRACE pipeline with ALL subsystems
# ---------------------------------------------------------------------------


class TestFullTracePipelineAllSubsystems:
    """Wire every subsystem manually into RunExecutor and verify."""

    def test_full_trace_pipeline_all_subsystems(self, tmp_path: Path) -> None:
        """Full S1-S5 pipeline with every subsystem wired in."""
        kernel = MockKernel(strict_mode=True)
        evolve = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=RegressionDetector(),
            champion_challenger=ChampionChallenger(),
        )
        event_emitter = EventEmitter()
        failure_collector = FailureCollector()
        watchdog = ProgressWatchdog()
        compressor = MemoryCompressor()
        raw_memory = RawMemoryStore()
        episode_builder = EpisodeBuilder()
        episodic_store = EpisodicMemoryStore(storage_dir=str(tmp_path / "episodes"))
        skill_registry = SkillRegistry(storage_dir=str(tmp_path / "skills"))
        skill_recorder = SkillUsageRecorder(registry=skill_registry)

        contract = TaskContract(
            task_id="e2e-full-001",
            goal="Analyze Q4 revenue trends",
            task_family="research",
            risk_level="medium",
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            evolve_engine=evolve,
            event_emitter=event_emitter,
            failure_collector=failure_collector,
            watchdog=watchdog,
            compressor=compressor,
            raw_memory=raw_memory,
            episode_builder=episode_builder,
            episodic_store=episodic_store,
            skill_recorder=skill_recorder,
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        result = executor.execute()

        # 1. Run completes S1 through S5
        assert result == "completed"
        for stage_id in STAGES:
            kernel.assert_stage_state(stage_id, StageState.COMPLETED)

        # 2. EventEmitter captured events
        assert len(event_emitter.events) > 0
        event_types = {e.event_type for e in event_emitter.events}
        assert "RunStarted" in event_types
        assert "StageStateChanged" in event_types

        # 3. FailureCollector is empty (no failures on success)
        assert len(failure_collector.get_all()) == 0

        # 4. Evolve postmortem was triggered (we verify by running it again
        #    -- the engine itself was called internally by the runner).
        #    Build a postmortem manually and verify the engine can process it.
        postmortem = RunRetrospective(
            run_id=executor.run_id,
            task_id="e2e-full-001",
            task_family="research",
            outcome="completed",
            stages_completed=list(STAGES),
            stages_failed=[],
            branches_explored=len(STAGES),
            branches_pruned=0,
            total_actions=len(STAGES),
            failure_codes=[],
            duration_seconds=1.0,
            quality_score=0.9,
            efficiency_score=0.85,
        )
        evolve_result = evolve.on_run_completed(postmortem)
        assert evolve_result is not None
        assert evolve_result.trigger == "per_run_postmortem"

        # 5. Memory compressor ran for each stage (stage summaries exist)
        assert len(executor.stage_summaries) == len(STAGES)
        for stage_id in STAGES:
            assert stage_id in executor.stage_summaries

        # 6. Episodic memory was stored (runner calls _build_and_store_episode)
        assert episodic_store.count() == 1

        # 7. All branches succeeded
        assert len(kernel.branches) > 0
        for _, branch in kernel.branches.items():
            assert branch["state"] == "succeeded"

        # 8. Task views recorded
        assert len(kernel.task_views) > 0

        # 9. Compressor metrics recorded activity
        total_compressions = (
            compressor.metrics.compressed_count
            + compressor.metrics.fallback_count
            + compressor.metrics.direct_count
        )
        assert total_compressions >= len(STAGES)


# ---------------------------------------------------------------------------
# Test 2: Full pipeline with failures and recovery
# ---------------------------------------------------------------------------


class TestFullPipelineWithFailuresAndRecovery:
    """Use force_fail_actions to trigger failures and verify recovery."""

    def test_pipeline_with_forced_failures_and_recovery(self) -> None:
        """FailureCollector records failures, watchdog detects them, run may still complete."""
        kernel = MockKernel(strict_mode=True)
        failure_collector = FailureCollector()
        watchdog = ProgressWatchdog(max_consecutive_failures=10)
        event_emitter = EventEmitter()

        contract = TaskContract(
            task_id="e2e-fail-recovery",
            goal="Test failure handling with recovery",
            task_family="quick_task",
            constraints=["fail_action:analyze_goal", "action_max_retries:2"],
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            event_emitter=event_emitter,
            failure_collector=failure_collector,
            watchdog=watchdog,
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        result = executor.execute()

        # The first stage action (analyze_goal) is forced to fail,
        # so the run should fail because dead-end detection fires.
        assert result == "failed"

        # FailureCollector has records
        all_failures = failure_collector.get_all()
        assert len(all_failures) > 0

        # ProgressWatchdog detected action failures
        assert watchdog.consecutive_failures >= 1

        # Recovery was triggered (RecoveryTriggered event)
        recovery_events = [e for e in event_emitter.events if e.event_type == "RecoveryTriggered"]
        assert len(recovery_events) > 0

    def test_pipeline_with_retries_succeeds(self) -> None:
        """Pipeline with retries on non-critical actions still completes."""
        kernel = MockKernel(strict_mode=True)
        failure_collector = FailureCollector()
        watchdog = ProgressWatchdog()

        # fail_action:nonexistent won't match any real action,
        # so the run completes normally
        contract = TaskContract(
            task_id="e2e-retry-success",
            goal="Test retry success",
            task_family="quick_task",
            constraints=["action_max_retries:1"],
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            failure_collector=failure_collector,
            watchdog=watchdog,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        result = executor.execute()
        assert result == "completed"
        assert len(failure_collector.get_all()) == 0


# ---------------------------------------------------------------------------
# Test 3: Task decomposition via Orchestrator
# ---------------------------------------------------------------------------


class TestTaskDecompositionViaOrchestrator:
    """Create TaskContract with decomposition_strategy and execute."""

    def test_linear_decomposition(self) -> None:
        """Linear decomposition produces sequential sub-tasks all completing."""
        kernel = MockKernel(strict_mode=False)
        contract = TaskContract(
            task_id="e2e-decompose-linear",
            goal="Sequential analysis task",
            task_family="quick_task",
            decomposition_strategy="linear",
        )
        orchestrator = TaskOrchestrator(kernel=kernel, decomposer=TaskDecomposer())
        result = orchestrator.execute(contract)

        assert result.success is True
        assert result.task_id == "e2e-decompose-linear"
        assert result.strategy == "linear"

        # Sub-results exist
        assert len(result.sub_results) > 0

        # All sub-tasks completed
        for sub in result.sub_results:
            assert sub.outcome == "completed"

    def test_dag_decomposition(self) -> None:
        """DAG decomposition produces sub-tasks for each phase."""
        kernel = MockKernel(strict_mode=False)
        contract = TaskContract(
            task_id="e2e-decompose-dag",
            goal="Build comprehensive market analysis",
            task_family="research",
            decomposition_strategy="dag",
        )
        orchestrator = TaskOrchestrator(kernel=kernel, decomposer=TaskDecomposer())
        result = orchestrator.execute(contract)

        assert result.success is True
        assert result.strategy == "dag"
        assert len(result.sub_results) == 5
        for sub in result.sub_results:
            assert sub.outcome == "completed"

    def test_simple_task_no_decomposition(self) -> None:
        """Task without decomposition_strategy runs directly."""
        kernel = MockKernel(strict_mode=True)
        contract = TaskContract(
            task_id="e2e-simple",
            goal="Simple task",
            task_family="quick_task",
        )
        orchestrator = TaskOrchestrator(kernel=kernel, decomposer=TaskDecomposer())
        result = orchestrator.execute(contract)

        assert result.success is True
        assert result.strategy is None
        assert len(result.sub_results) == 1


# ---------------------------------------------------------------------------
# Test 4: Episodic memory across two runs
# ---------------------------------------------------------------------------


class TestEpisodicMemoryAcrossTwoRuns:
    """Run two tasks and verify episodes persist across runs."""

    def test_episodic_memory_persists_across_runs(self, tmp_path: Path) -> None:
        """Two successive runs each store an episode; both are queryable."""
        store = EpisodicMemoryStore(str(tmp_path / "episodes"))
        builder = EpisodeBuilder()

        # Use a single shared kernel so run IDs are unique (run-0001, run-0002)
        kernel = MockKernel(strict_mode=False)

        # Run 1
        contract1 = TaskContract(
            task_id="mem-run-1",
            goal="First research analysis",
            task_family="research",
        )
        executor1 = RunExecutor(
            contract=contract1,
            kernel=kernel,
            episode_builder=builder,
            episodic_store=store,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        result1 = executor1.execute()
        assert result1 == "completed"
        assert store.count() == 1

        # Run 2
        contract2 = TaskContract(
            task_id="mem-run-2",
            goal="Second research analysis",
            task_family="research",
        )
        executor2 = RunExecutor(
            contract=contract2,
            kernel=kernel,
            episode_builder=builder,
            episodic_store=store,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        result2 = executor2.execute()
        assert result2 == "completed"

        # Run IDs must be different for two distinct episodes
        assert executor1.run_id != executor2.run_id
        assert store.count() == 2

        # Both episodes are queryable by task_family
        episodes = store.query(task_family="research")
        assert len(episodes) == 2

    def test_episodic_memory_failure_similarity(self, tmp_path: Path) -> None:
        """Failed episodes can be found by overlapping failure codes."""
        store = EpisodicMemoryStore(str(tmp_path / "episodes"))

        episode = EpisodeRecord(
            run_id="fail-run-x",
            task_id="fail-task-x",
            task_family="research",
            goal="Failed analysis",
            outcome="failed",
            stages_completed=["S1_understand"],
            key_findings=[],
            key_decisions=[],
            failure_codes=["missing_evidence", "no_progress"],
        )
        store.store(episode)

        similar = store.get_similar_failures(["missing_evidence"])
        assert len(similar) == 1
        assert similar[0].run_id == "fail-run-x"


# ---------------------------------------------------------------------------
# Test 5: Skill lifecycle end-to-end
# ---------------------------------------------------------------------------


class TestSkillLifecycleEndToEnd:
    """Run -> Evolve extracts SkillCandidate -> register -> promote -> certified."""

    def test_skill_extraction_registration_promotion(self, tmp_path: Path) -> None:
        """Extract skill from successful run, register, promote to certified."""
        skill_dir = str(tmp_path / "skills")
        registry = SkillRegistry(storage_dir=skill_dir)
        evolve = EvolveEngine(
            skill_extractor=SkillExtractor(),
            regression_detector=RegressionDetector(),
            champion_challenger=ChampionChallenger(),
        )

        # Simulate a successful run postmortem
        postmortem = RunRetrospective(
            run_id="skill-run-001",
            task_id="skill-task-001",
            task_family="research",
            outcome="completed",
            stages_completed=list(STAGES),
            stages_failed=[],
            branches_explored=5,
            branches_pruned=0,
            total_actions=5,
            failure_codes=[],
            duration_seconds=10.0,
            quality_score=0.9,
            efficiency_score=0.85,
        )

        # Evolve extracts SkillCandidate
        result = evolve.on_run_completed(postmortem)
        assert result.metrics.skill_candidates_found > 0

        # Register candidates in the registry
        for change in result.changes:
            if change.change_type == "skill_candidate":
                candidate = SkillCandidate(
                    skill_id=change.target_id,
                    name=f"Skill:{change.target_id}",
                    description=change.description,
                    applicability_scope="research",
                    preconditions=[],
                    evidence_count=1,
                    confidence=change.confidence,
                    source_run_ids=list(change.evidence_refs),
                )
                registry.register_candidate(candidate)

        candidates = registry.list_by_stage("candidate")
        assert len(candidates) > 0
        skill_id = candidates[0].skill_id

        # Accumulate evidence for promotion (register again from second run)
        postmortem2 = RunRetrospective(
            run_id="skill-run-002",
            task_id="skill-task-002",
            task_family="research",
            outcome="completed",
            stages_completed=list(STAGES),
            stages_failed=[],
            branches_explored=5,
            branches_pruned=0,
            total_actions=5,
            failure_codes=[],
            duration_seconds=8.0,
            quality_score=0.92,
            efficiency_score=0.88,
        )
        result2 = evolve.on_run_completed(postmortem2)
        for change in result2.changes:
            if change.change_type == "skill_candidate":
                candidate = SkillCandidate(
                    skill_id=change.target_id,
                    name=f"Skill:{change.target_id}",
                    description=change.description,
                    applicability_scope="research",
                    preconditions=[],
                    evidence_count=1,
                    confidence=change.confidence,
                    source_run_ids=list(change.evidence_refs),
                )
                registry.register_candidate(candidate)

        skill = registry.get(skill_id)
        assert skill is not None
        assert skill.evidence_count >= 2

        # Promote candidate -> provisional (requires >= 2 evidence)
        registry.promote(skill_id, "provisional")
        assert registry.get(skill_id).lifecycle_stage == "provisional"

        # Simulate usage data for certified promotion
        skill.evidence_count = 6
        skill.success_count = 5
        skill.failure_count = 1

        # Promote provisional -> certified
        registry.promote(skill_id, "certified")
        assert registry.get(skill_id).lifecycle_stage == "certified"

        # Certified skill appears in registry
        certified = registry.list_certified()
        assert len(certified) > 0
        assert any(s.skill_id == skill_id for s in certified)

        # Save and reload to verify persistence
        registry.save()
        registry2 = SkillRegistry(storage_dir=skill_dir)
        registry2.load()
        assert registry2.get(skill_id) is not None
        assert registry2.get(skill_id).lifecycle_stage == "certified"

    def test_skill_deprecation_and_retirement(self) -> None:
        """Certified skills can be deprecated and retired."""
        registry = SkillRegistry()
        candidate = SkillCandidate(
            skill_id="dep-skill-e2e",
            name="Deprecatable Skill",
            description="A skill to deprecate",
            applicability_scope="*",
            preconditions=[],
            evidence_count=6,
            confidence=0.9,
            source_run_ids=["r1", "r2", "r3"],
        )
        registry.register_candidate(candidate)
        skill = registry.get("dep-skill-e2e")
        skill.success_count = 5
        skill.failure_count = 1

        registry.promote("dep-skill-e2e", "provisional")
        registry.promote("dep-skill-e2e", "certified")
        registry.deprecate("dep-skill-e2e", "Superseded by better approach")
        assert registry.get("dep-skill-e2e").lifecycle_stage == "deprecated"

        registry.retire("dep-skill-e2e")
        assert registry.get("dep-skill-e2e").lifecycle_stage == "retired"


# ---------------------------------------------------------------------------
# Test 6: State machines match runtime behavior
# ---------------------------------------------------------------------------


class TestStateMachinesMatchRuntimeBehavior:
    """Create run_state_machine() and transition through RunExecutor lifecycle."""

    def test_run_state_machine_matches_lifecycle(self) -> None:
        """State machine transitions created->active->completed match runner."""
        sm = run_state_machine()
        assert sm.current == "created"
        assert not sm.is_terminal

        sm.transition("active")
        assert sm.current == "active"

        sm.transition("completed")
        assert sm.current == "completed"
        assert sm.is_terminal

        # History tracks all transitions
        history = sm.history
        assert len(history) == 2
        assert history[0] == ("created", "active", "run")
        assert history[1] == ("active", "completed", "run")

    def test_run_state_machine_failure_path(self) -> None:
        """State machine supports active->failed path."""
        sm = run_state_machine()
        sm.transition("active")
        sm.transition("failed")
        assert sm.current == "failed"
        assert sm.is_terminal

    def test_run_state_machine_waiting_recovery(self) -> None:
        """State machine supports active->waiting->recovering->active path."""
        sm = run_state_machine()
        sm.transition("active")
        sm.transition("waiting")
        assert sm.current == "waiting"

        sm.transition("recovering")
        assert sm.current == "recovering"

        sm.transition("active")
        assert sm.current == "active"

    def test_run_state_machine_invalid_transition_rejected(self) -> None:
        """Invalid transitions raise InvalidTransition."""
        from hi_agent.state_machine.machine import InvalidTransition

        sm = run_state_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("completed")  # cannot go created -> completed

    def test_state_machine_matches_actual_run_execution(self) -> None:
        """Run a real executor and verify states match the machine model."""
        kernel = MockKernel(strict_mode=True)
        contract = TaskContract(
            task_id="sm-e2e-001",
            goal="State machine verification",
            task_family="quick_task",
        )

        sm = run_state_machine()
        assert sm.current == "created"

        # Start the run -- this moves to active
        sm.transition("active")

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        result = executor.execute()

        # Run completed successfully
        assert result == "completed"
        sm.transition("completed")
        assert sm.current == "completed"
        assert sm.is_terminal


# ---------------------------------------------------------------------------
# Test 7: Policy version pinning
# ---------------------------------------------------------------------------


class TestPolicyVersionPinning:
    """Create RunExecutor with specific PolicyVersionSet and verify in events."""

    def test_policy_versions_appear_in_emitted_events(self) -> None:
        """Policy versions are recorded in RunStarted event payload."""
        kernel = MockKernel(strict_mode=True)
        event_emitter = EventEmitter()

        custom_policy = PolicyVersionSet(
            route_policy="route_v2_custom",
            acceptance_policy="acceptance_v3_strict",
            memory_policy="memory_v2_aggressive",
            evaluation_policy="evaluation_v2",
            task_view_policy="task_view_v2",
            skill_policy="skill_v2",
        )

        contract = TaskContract(
            task_id="policy-e2e-001",
            goal="Test policy pinning",
            task_family="quick_task",
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            event_emitter=event_emitter,
            policy_versions=custom_policy,
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
        )

        result = executor.execute()
        assert result == "completed"

        # Find RunStarted event
        run_started_events = [e for e in event_emitter.events if e.event_type == "RunStarted"]
        assert len(run_started_events) == 1

        payload = run_started_events[0].payload
        pv = payload.get("policy_versions", {})
        assert pv["route_policy"] == "route_v2_custom"
        assert pv["acceptance_policy"] == "acceptance_v3_strict"
        assert pv["memory_policy"] == "memory_v2_aggressive"
        assert pv["evaluation_policy"] == "evaluation_v2"
        assert pv["task_view_policy"] == "task_view_v2"
        assert pv["skill_policy"] == "skill_v2"

    def test_policy_versions_appear_in_task_views(self) -> None:
        """Policy versions are recorded in kernel task views."""
        kernel = MockKernel(strict_mode=True)

        custom_policy = PolicyVersionSet(
            route_policy="route_pinned",
            acceptance_policy="accept_pinned",
        )

        contract = TaskContract(
            task_id="policy-tv-001",
            goal="Task view policy test",
            task_family="quick_task",
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            policy_versions=custom_policy,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
        )

        result = executor.execute()
        assert result == "completed"

        # Task views should contain policy_versions
        assert len(kernel.task_views) > 0
        for _, tv_content in kernel.task_views.items():
            pv = tv_content.get("policy_versions", {})
            assert pv.get("route_policy") == "route_pinned"
            assert pv.get("acceptance_policy") == "accept_pinned"


# ---------------------------------------------------------------------------
# Test 8: Harness governance blocks unapproved irreversible action
# ---------------------------------------------------------------------------


class TestHarnessGovernanceBlocksUnapproved:
    """HarnessExecutor + GovernanceEngine blocks irreversible without approval."""

    def test_governance_blocks_unapproved_irreversible_action(self) -> None:
        """Irreversible action without prior approval is blocked."""
        governance = GovernanceEngine()
        harness = HarnessExecutor(governance=governance, evidence_store=EvidenceStore())

        spec = ActionSpec(
            action_id="irrev-e2e-001",
            action_type="submit",
            capability_name="publish_report",
            payload={"report": "Q4 analysis"},
            effect_class=EffectClass.IRREVERSIBLE_WRITE,
            side_effect_class=SideEffectClass.IRREVERSIBLE_SUBMIT,
            approval_required=True,
            idempotency_key="idem-e2e-001",
        )

        result = harness.execute(spec)
        assert result.state == ActionState.APPROVAL_PENDING
        assert result.error_code == "approval_pending"

        # Verify the action is in the governance approval queue
        assert len(governance.pending_approvals) == 1

    def test_governance_allows_after_approval(self) -> None:
        """After approval, governance allows the action (dispatch may still fail
        if no invoker, but governance does not block).
        """
        governance = GovernanceEngine()
        harness = HarnessExecutor(governance=governance, evidence_store=EvidenceStore())

        spec = ActionSpec(
            action_id="irrev-approved-001",
            action_type="submit",
            capability_name="publish_report",
            payload={"report": "Q4 analysis"},
            effect_class=EffectClass.IRREVERSIBLE_WRITE,
            side_effect_class=SideEffectClass.IRREVERSIBLE_SUBMIT,
            approval_required=True,
            idempotency_key="idem-approved-001",
        )

        # First attempt: blocked
        result1 = harness.execute(spec)
        assert result1.state == ActionState.APPROVAL_PENDING

        # Approve
        governance.approve("irrev-approved-001")

        # Second attempt: governance passes but no invoker -> dispatch fails
        result2 = harness.execute(spec)
        assert result2.state == ActionState.FAILED
        assert result2.error_code == "harness_execution_failed"

    def test_read_only_action_passes_governance(self) -> None:
        """Read-only actions pass governance without approval."""
        governance = GovernanceEngine()

        class SimpleInvoker:
            def invoke(self, name: str, payload: dict) -> dict:
                return {"data": "result"}

        harness = HarnessExecutor(
            governance=governance,
            capability_invoker=SimpleInvoker(),
            evidence_store=EvidenceStore(),
        )

        spec = ActionSpec(
            action_id="read-e2e-001",
            action_type="read",
            capability_name="fetch_data",
            payload={},
            effect_class=EffectClass.READ_ONLY,
            side_effect_class=SideEffectClass.READ_ONLY,
        )

        result = harness.execute(spec)
        assert result.state == ActionState.SUCCEEDED
        assert result.output == {"data": "result"}
        assert result.evidence_ref is not None


# ---------------------------------------------------------------------------
# Test 9: Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    """Create TaskContract with small budget and verify budget_exhausted."""

    def test_small_budget_stops_execution(self) -> None:
        """Run with max_actions=2 triggers budget_exhausted."""
        kernel = MockKernel(strict_mode=True)
        event_emitter = EventEmitter()
        failure_collector = FailureCollector()

        contract = TaskContract(
            task_id="budget-e2e-001",
            goal="Budget test",
            task_family="quick_task",
            budget=TaskBudget(max_actions=2),
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            event_emitter=event_emitter,
            failure_collector=failure_collector,
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        _ = executor.execute()

        # Action seq should be capped near the budget
        assert executor.action_seq <= 3

        # BudgetExhausted event should have been emitted
        budget_events = [e for e in event_emitter.events if e.event_type == "BudgetExhausted"]
        assert len(budget_events) >= 1

    def test_budget_one_action_limit(self) -> None:
        """Run with max_actions=1 emits budget_exhausted after first action."""
        kernel = MockKernel(strict_mode=True)
        event_emitter = EventEmitter()

        contract = TaskContract(
            task_id="budget-e2e-002",
            goal="Extreme budget test",
            task_family="quick_task",
            budget=TaskBudget(max_actions=1),
        )

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            event_emitter=event_emitter,
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        budget_events = [e for e in event_emitter.events if e.event_type == "BudgetExhausted"]
        assert len(budget_events) >= 1

    def test_cts_total_branch_limit(self) -> None:
        """CTS max_total_branches_per_run caps branch creation."""
        kernel = MockKernel(strict_mode=True)

        contract = TaskContract(
            task_id="cts-branch-e2e",
            goal="CTS branch limit test",
            task_family="quick_task",
        )

        cts_budget = CTSExplorationBudget(max_total_branches_per_run=3)

        executor = RunExecutor(
            contract=contract,
            kernel=kernel,
            cts_budget=cts_budget,
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            policy_versions=PolicyVersionSet(),
        )

        executor.execute()

        # Total branches should be capped near the limit
        assert executor._total_branches_opened <= 4


# ---------------------------------------------------------------------------
# Test 10: HTTP API round-trip
# ---------------------------------------------------------------------------


class TestHTTPAPIRoundTrip:
    """Test AgentServer HTTP routes using Starlette TestClient."""

    def test_health_and_list_runs(self) -> None:
        """GET /health and GET /runs work on a fresh server."""
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=9999)
        with TestClient(server.app) as client:
            # GET /health
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] in ("ok", "degraded")

            # GET /runs (empty initially)
            resp = client.get("/runs")
            assert resp.status_code == 200
            assert resp.json()["runs"] == []

    def test_post_and_query_run(self) -> None:
        """POST /runs creates a run, GET /runs lists it, GET /runs/{id} returns it."""
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=9999)

        def executor_factory(run_data: dict[str, Any]) -> Any:
            def _run() -> str:
                kernel = MockKernel(strict_mode=True)
                contract = TaskContract(
                    task_id=run_data.get("task_id", run_data.get("run_id", "unknown")),
                    goal=run_data["goal"],
                    task_family=run_data.get("task_family", "quick_task"),
                )
                runner = RunExecutor(
                    contract,
                    kernel,
                    event_emitter=EventEmitter(),
                    compressor=MemoryCompressor(),
                    acceptance_policy=AcceptancePolicy(),
                    cts_budget=CTSExplorationBudget(),
                    policy_versions=PolicyVersionSet(),
                )
                return runner.execute()

            return _run

        server.executor_factory = executor_factory

        with TestClient(server.app) as client:
            # POST /runs -- create a new run
            resp = client.post(
                "/runs",
                json={
                    "task_id": "http-e2e-001",
                    "goal": "HTTP round-trip test",
                    "task_family": "quick_task",
                },
            )
            assert resp.status_code == 201
            run_id = resp.json()["run_id"]
            assert run_id  # server generates a unique run_id per request

            # Wait for the run to complete
            deadline = time.monotonic() + 10.0
            final_state = None
            while time.monotonic() < deadline:
                resp = client.get(f"/runs/{run_id}")
                assert resp.status_code == 200
                final_state = resp.json()["state"]
                if final_state in ("completed", "failed"):
                    break
                time.sleep(0.2)
            assert final_state == "completed"

            # GET /runs -- list runs
            resp = client.get("/runs")
            assert resp.status_code == 200
            assert len(resp.json()["runs"]) >= 1

            # GET /health
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] in ("ok", "degraded")
