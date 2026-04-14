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
    from hi_agent.observability.trajectory_exporter import TrajectoryExporter
    from hi_agent.session.run_session import RunSession
    from hi_agent.skill.evolver import SkillEvolver

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
        route_engine: Any | None = None,
        tier_router: Any | None = None,
        trajectory_exporter: "TrajectoryExporter | None" = None,
        trajectory_export_dir: str = ".hi_agent/trajectories",
        trajectory_export_enabled: bool = True,
        skill_evolver: "SkillEvolver | None" = None,
        skill_evolve_interval: int = 10,
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
        self.route_engine = route_engine
        self.tier_router = tier_router
        self.trajectory_exporter = trajectory_exporter
        self.trajectory_export_dir = trajectory_export_dir
        self._trajectory_export_enabled = trajectory_export_enabled
        self.skill_evolver = skill_evolver
        self._skill_evolve_interval = skill_evolve_interval
        self._evolve_run_count: int = 0

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
        skill_ids_used: list[str] | None = None,
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

        # quality_score: outcome-based heuristic (0=failed, 0.5=partial, 1=completed)
        if outcome == "completed":
            quality_score: float | None = 1.0
        elif outcome == "failed":
            quality_score = 0.0
        else:
            quality_score = 0.5

        # efficiency_score: ratio of stages completed vs total actions taken
        total_stages = len(stages_completed) + len(stages_failed)
        if total_stages > 0 and action_seq > 0:
            efficiency_score: float | None = min(
                1.0, len(stages_completed) / max(action_seq, total_stages)
            )
        else:
            efficiency_score = None

        # trajectory_summary: brief textual summary
        trajectory_summary = (
            f"outcome={outcome} stages_completed={len(stages_completed)} "
            f"stages_failed={len(stages_failed)} "
            f"branches={branches_explored} actions={action_seq}"
        )

        # Backfill duration_seconds from kernel's authoritative timestamps.
        # query_run_postmortem() now returns real created_at/completed_at after
        # the agent-kernel P0 fix (commit a43c9c4a).  Fall back to 0.0 if the
        # kernel is unavailable or the run hasn't been started via kernel yet.
        duration_seconds: float = 0.0
        if kernel is not None and hasattr(kernel, "query_run_postmortem"):
            try:
                pv = kernel.query_run_postmortem(run_id)
                if pv is not None:
                    raw_ms = getattr(pv, "duration_ms", None)
                    if raw_ms and raw_ms > 0:
                        duration_seconds = raw_ms / 1000.0
            except Exception as exc:
                _logger.debug(
                    "run.postmortem_kernel_duration_failed run_id=%s error=%s",
                    run_id,
                    exc,
                )

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
            duration_seconds=duration_seconds,
            quality_score=quality_score,
            efficiency_score=efficiency_score,
            trajectory_summary=trajectory_summary,
            skills_used=list(skill_ids_used) if skill_ids_used else [],
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
                    skill_ids_used=skill_ids_used,
                )
                evolve_result = self.evolve_engine.on_run_completed(postmortem)
                if evolve_result.changes:
                    _logger.info(
                        "run.evolve_changes run_id=%s changes=%d",
                        run_id,
                        len(evolve_result.changes),
                    )
                    for change in evolve_result.changes:
                        _logger.debug(
                            "evolve_change type=%s target=%s confidence=%.2f",
                            change.change_type,
                            change.target_id,
                            change.confidence,
                        )
                    if self.route_engine is not None:
                        try:
                            self.route_engine.apply_evolve_changes(evolve_result.changes)
                        except Exception as exc:
                            _logger.warning(
                                "run.apply_evolve_changes_failed run_id=%s error=%s",
                                run_id,
                                exc,
                            )
                # Check for regression after recording this run's metrics.
                if contract is not None:
                    try:
                        reg = self.evolve_engine.check_regression(contract.task_family)
                        if reg.is_regression:
                            _logger.warning(
                                "run.regression_detected run_id=%s task_family=%s "
                                "quality_delta=%.3f recommendation=%s",
                                run_id,
                                contract.task_family,
                                reg.quality_delta,
                                reg.recommendation,
                            )
                    except Exception as reg_exc:
                        _logger.debug(
                            "run.regression_check_failed run_id=%s error=%s",
                            run_id,
                            reg_exc,
                        )
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
        # Best-effort cost optimization hints → apply to TierRouter (P2 feedback loop)
        if self.session is not None:
            try:
                from hi_agent.session.cost_optimizer import (
                    derive_tier_overrides,
                    recommend_cost_optimizations,
                )
                summary = self.session.get_cost_summary()
                # Get cumulative run count from metrics collector so that
                # historical-trend thresholds in cost_optimizer can trigger.
                run_count = 1  # default for first/isolated run
                if (
                    hasattr(self, "metrics_collector")
                    and self.metrics_collector is not None
                ):
                    run_count = max(1, self.metrics_collector.completed_run_count)
                hints = recommend_cost_optimizations(
                    run_count=run_count,
                    avg_cost_per_run=summary.get("total_usd", 0.0),
                    per_model_breakdown=summary.get("per_model", {}),
                )
                if hints:
                    _logger.info("run.cost_hints run_id=%s hints=%d", run_id, len(hints))
                    for h in hints:
                        _logger.debug(
                            "cost_hint code=%s severity=%s action=%s",
                            h.code,
                            h.severity,
                            h.action,
                        )
                    # Apply tier overrides so the next run immediately benefits
                    if self.tier_router is not None:
                        overrides = derive_tier_overrides(hints)
                        if overrides:
                            self.tier_router.apply_overrides(overrides)
                            _logger.info(
                                "run.tier_overrides_applied run_id=%s overrides=%s",
                                run_id,
                                overrides,
                            )
            except Exception as exc:
                _logger.debug("run.cost_hints_failed run_id=%s error=%s", run_id, exc)
        sync_to_context_fn()
        # Auto-export trajectory for RL training (only when enabled via config)
        trajectory_enabled = getattr(self, '_trajectory_export_enabled', True)
        if trajectory_enabled and self.trajectory_exporter is not None and self.session is not None:
            try:
                output_path = f"{self.trajectory_export_dir}/{run_id}.jsonl"
                self.trajectory_exporter.export_session(
                    self.session.to_checkpoint(), output_path
                )
            except Exception as exc:
                _logger.debug(
                    "trajectory_export_failed run_id=%s error=%s", run_id, exc
                )
        # Auto-trigger skill evolve_cycle every N runs
        if self.skill_evolver is not None:
            self._evolve_run_count += 1
            if self._evolve_run_count % self._skill_evolve_interval == 0:
                try:
                    result = self.skill_evolver.evolve_cycle()
                    _logger.info(
                        "skill_evolve_cycle completed changes=%d",
                        len(result.details) if result else 0,
                    )
                except Exception as exc:
                    _logger.debug("skill_evolve_cycle_failed error=%s", exc)
        return outcome
