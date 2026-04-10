"""Run lifecycle delegation extracted from RunExecutor.

This module contains the RunLifecycle helper class which encapsulates
run finalization (STM save, knowledge ingest, evolve, memory lifecycle),
checkpoint resume, budget checking, and postmortem building.
RunExecutor delegates to an instance of this class.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hi_agent.contracts import (
    CTSExplorationBudget,
    NodeState,
    StageState,
    StageSummary,
    TaskContract,
)
from hi_agent.failures.taxonomy import FailureCode

if TYPE_CHECKING:
    from hi_agent.evolve.contracts import RunPostmortem
    from hi_agent.evolve.engine import EvolveEngine
    from hi_agent.failures.collector import FailureCollector
    from hi_agent.memory.episode_builder import EpisodeBuilder
    from hi_agent.memory.episodic import EpisodicMemoryStore
    from hi_agent.memory.short_term import ShortTermMemoryStore
    from hi_agent.session.run_session import RunSession

from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.memory import RawMemoryStore

_logger = logging.getLogger(__name__)


class RunLifecycle:
    """Encapsulates run finalization, budget checking, and postmortem."""

    def __init__(
        self,
        *,
        session: RunSession | None,
        short_term_store: ShortTermMemoryStore | None,
        knowledge_manager: Any | None,
        evolve_engine: EvolveEngine | None,
        memory_lifecycle_manager: Any | None,
        budget_guard: Any | None,
        episode_builder: EpisodeBuilder | None,
        episodic_store: EpisodicMemoryStore | None,
        failure_collector: FailureCollector | None,
        raw_memory: RawMemoryStore,
        cts_budget: CTSExplorationBudget,
    ) -> None:
        self.session = session
        self.short_term_store = short_term_store
        self.knowledge_manager = knowledge_manager
        self.evolve_engine = evolve_engine
        self.memory_lifecycle_manager = memory_lifecycle_manager
        self.budget_guard = budget_guard
        self.episode_builder = episode_builder
        self.episodic_store = episodic_store
        self.failure_collector = failure_collector
        self.raw_memory = raw_memory
        self.cts_budget = cts_budget

    # ------------------------------------------------------------------
    # Budget checking
    # ------------------------------------------------------------------

    def check_budget_exceeded(
        self,
        stage_id: str,
        *,
        action_seq: int,
        contract: TaskContract,
        stage_active_branches: dict[str, int],
        total_branches_opened: int,
    ) -> str | None:
        """Return a failure code if any CTS or task budget limit is exceeded.

        Returns:
            A standard failure code string, or ``None`` if all budgets
            are within limits.
        """
        # --- Task-level action budget ---
        task_budget = contract.budget
        if task_budget is not None and action_seq >= task_budget.max_actions:
            return FailureCode.EXECUTION_BUDGET_EXHAUSTED.value

        # --- CTS branch-per-stage limit ---
        active_in_stage = stage_active_branches.get(stage_id, 0)
        if active_in_stage >= self.cts_budget.max_active_branches_per_stage:
            return FailureCode.EXPLORATION_BUDGET_EXHAUSTED.value

        # --- CTS total branches across run ---
        if total_branches_opened >= self.cts_budget.max_total_branches_per_run:
            return FailureCode.EXPLORATION_BUDGET_EXHAUSTED.value

        return None

    # ------------------------------------------------------------------
    # Episode building
    # ------------------------------------------------------------------

    def build_and_store_episode(
        self,
        outcome: str,
        *,
        run_id: str,
        contract: TaskContract,
        stage_summaries: dict[str, StageSummary],
    ) -> None:
        """Build and store episode after run completes (best-effort)."""
        if self.episode_builder is None or self.episodic_store is None:
            return
        try:
            failure_codes: list[str] = []
            if self.failure_collector is not None:
                failure_codes = self.failure_collector.get_failure_codes()

            episode = self.episode_builder.build(
                run_id=run_id,
                task_contract=contract,
                stage_summaries=stage_summaries,
                outcome=outcome,
                failure_codes=failure_codes,
            )
            self.episodic_store.store(episode)
        except Exception as exc:
            _logger.warning(
                "run.episode_store_failed run_id=%s task_id=%s outcome=%s error=%s",
                run_id,
                contract.task_id,
                outcome,
                exc,
            )

    # ------------------------------------------------------------------
    # Postmortem
    # ------------------------------------------------------------------

    def build_postmortem(
        self,
        outcome: str,
        *,
        run_id: str,
        contract: TaskContract,
        stage_summaries: dict[str, StageSummary],
        dag: dict,
        action_seq: int,
        policy_versions: PolicyVersionSet,
        kernel: Any,
    ) -> RunPostmortem:
        """Build a RunPostmortem from current run state."""
        from hi_agent.evolve.contracts import RunPostmortem

        stages_completed: list[str] = []
        stages_failed: list[str] = []
        for sid in stage_summaries:
            stage_state = kernel.stages.get(sid) if hasattr(kernel, "stages") else None
            if stage_state == StageState.FAILED:
                stages_failed.append(sid)
            elif stage_state == StageState.COMPLETED:
                stages_completed.append(sid)
            else:
                if stage_summaries[sid].outcome == "failed":
                    stages_failed.append(sid)
                else:
                    stages_completed.append(sid)

        branches_explored = 0
        branches_pruned = 0
        for node in dag.values():
            branches_explored += 1
            if node.state == NodeState.PRUNED:
                branches_pruned += 1

        failure_codes: list[str] = []
        if self.failure_collector is not None:
            try:
                failure_codes = self.failure_collector.get_failure_codes()
            except Exception as exc:
                _logger.debug(
                    "run.postmortem_failure_codes_failed run_id=%s error=%s",
                    run_id,
                    exc,
                )
                failure_codes = []
        if not failure_codes:
            for record in self.raw_memory.list_all():
                code = record.payload.get("failure_code")
                if code and code not in failure_codes:
                    failure_codes.append(code)

        return RunPostmortem(
            run_id=run_id,
            task_id=contract.task_id,
            task_family=contract.task_family,
            outcome=outcome,
            stages_completed=stages_completed,
            stages_failed=stages_failed,
            branches_explored=branches_explored,
            branches_pruned=branches_pruned,
            total_actions=action_seq,
            failure_codes=failure_codes,
            duration_seconds=0.0,
            policy_versions={
                "route_policy": policy_versions.route_policy,
                "acceptance_policy": policy_versions.acceptance_policy,
                "memory_policy": policy_versions.memory_policy,
                "evaluation_policy": policy_versions.evaluation_policy,
                "task_view_policy": policy_versions.task_view_policy,
                "skill_policy": policy_versions.skill_policy,
            },
        )

    # ------------------------------------------------------------------
    # Run finalization
    # ------------------------------------------------------------------

    def finalize_run(
        self,
        outcome: str,
        *,
        run_id: str,
        current_stage: str,
        contract: TaskContract,
        stage_summaries: dict[str, StageSummary],
        dag: dict,
        action_seq: int,
        policy_versions: PolicyVersionSet,
        kernel: Any,
        skill_ids_used: list[str],
        emit_observability_fn,
        persist_snapshot_fn,
        finalize_skill_outcomes_fn,
        sync_to_context_fn,
    ) -> str:
        """Run post-execution finalization for a given outcome.

        Returns:
            The *outcome* string unchanged.
        """
        if outcome == "failed":
            emit_observability_fn(
                "run_failed",
                {"run_id": run_id, "stage_id": current_stage},
            )
        else:
            persist_snapshot_fn(
                stage_id=current_stage, result="completed"
            )
            emit_observability_fn(
                "run_completed",
                {"run_id": run_id, "stage_id": current_stage},
            )

        if self.evolve_engine is not None:
            try:
                postmortem = self.build_postmortem(
                    outcome,
                    run_id=run_id,
                    contract=contract,
                    stage_summaries=stage_summaries,
                    dag=dag,
                    action_seq=action_seq,
                    policy_versions=policy_versions,
                    kernel=kernel,
                )
                self.evolve_engine.on_run_completed(postmortem)
            except Exception as exc:
                _logger.warning(
                    "run.evolve_postmortem_failed run_id=%s stage_id=%s error=%s",
                    run_id,
                    current_stage,
                    exc,
                )
        finalize_skill_outcomes_fn(outcome)
        self.build_and_store_episode(
            outcome,
            run_id=run_id,
            contract=contract,
            stage_summaries=stage_summaries,
        )
        # Session: emit cost summary at run end
        if self.session is not None:
            try:
                cost = self.session.get_cost_summary()
                cost["run_id"] = run_id
                emit_observability_fn("run_cost_summary", cost)
            except Exception as exc:
                _logger.debug(
                    "run.cost_summary_failed run_id=%s stage_id=%s error=%s",
                    run_id,
                    current_stage,
                    exc,
                )
        # Build and store short-term memory from session
        if self.short_term_store is not None and self.session is not None:
            try:
                stm = self.short_term_store.build_from_session(self.session)
                self.short_term_store.save(stm)
                emit_observability_fn("short_term_memory_saved", {
                    "run_id": run_id,
                    "session_id": stm.session_id,
                    "outcome": stm.outcome,
                })
            except Exception as exc:
                _logger.debug(
                    "run.short_term_memory_save_failed run_id=%s stage_id=%s error=%s",
                    run_id,
                    current_stage,
                    exc,
                )
        # Auto-trigger dream/consolidation via lifecycle manager
        if self.memory_lifecycle_manager is not None:
            try:
                self.memory_lifecycle_manager.on_run_completed()
            except Exception as exc:
                _logger.debug(
                    "run.memory_lifecycle_failed run_id=%s stage_id=%s error=%s",
                    run_id,
                    current_stage,
                    exc,
                )
        # Auto-ingest session knowledge
        if self.knowledge_manager is not None and self.session is not None:
            try:
                count = self.knowledge_manager.ingest_from_session(self.session)
                emit_observability_fn("knowledge_ingested", {
                    "run_id": run_id, "items_ingested": count,
                })
            except Exception as exc:
                _logger.debug(
                    "run.knowledge_ingest_failed run_id=%s stage_id=%s error=%s",
                    run_id,
                    current_stage,
                    exc,
                )
        sync_to_context_fn()
        return outcome
