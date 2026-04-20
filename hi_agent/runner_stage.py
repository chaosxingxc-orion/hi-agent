"""Stage execution delegation extracted from RunExecutor.

This module contains the StageExecutor helper class which encapsulates
the ``_execute_stage()`` and ``_build_task_view_knowledge()`` logic.
RunExecutor delegates to an instance of this class.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from hi_agent.contracts import (
    BranchState,
    NodeState,
    NodeType,
    StageState,
    StageSummary,
    TrajectoryNode,
    deterministic_id,
)
from hi_agent.task_view.builder import (
    build_run_index,
    build_task_view_with_knowledge_query,
)
from hi_agent.trajectory.dead_end import detect_dead_end

if TYPE_CHECKING:
    from hi_agent.middleware.orchestrator import MiddlewareOrchestrator

_logger = logging.getLogger(__name__)

# Routing LLM call cost estimates — used when route_engine.propose() does not
# return token metadata.  Named constants so the magic numbers are explicit.
_ROUTING_ESTIMATED_INPUT_TOKENS: int = 500
_ROUTING_ESTIMATED_OUTPUT_TOKENS: int = 200
_ROUTING_ESTIMATED_TOTAL_TOKENS: int = _ROUTING_ESTIMATED_INPUT_TOKENS + _ROUTING_ESTIMATED_OUTPUT_TOKENS


class StageExecutor:
    """Encapsulates per-stage execution logic."""

    def __init__(
        self,
        *,
        kernel: Any,
        route_engine: Any,
        context_manager: Any | None,
        budget_guard: Any | None,
        optional_stages: set[str],
        acceptance_policy: Any,
        policy_versions: Any,
        knowledge_query_fn: Any | None,
        knowledge_query_text_builder: Any | None,
        retrieval_engine: Any | None,
        auto_compress: Any | None,
        cost_calculator: Any | None,
        middleware_orchestrator: MiddlewareOrchestrator | None = None,
        capability_registry: Any | None = None,
        capability_runtime_mode: str = "dev",
    ) -> None:
        self.kernel = kernel
        self.route_engine = route_engine
        self.context_manager = context_manager
        self.budget_guard = budget_guard
        self.optional_stages = optional_stages
        self.acceptance_policy = acceptance_policy
        self.policy_versions = policy_versions
        self.knowledge_query_fn = knowledge_query_fn
        self.knowledge_query_text_builder = knowledge_query_text_builder
        self.retrieval_engine = retrieval_engine
        self.auto_compress = auto_compress
        self.cost_calculator = cost_calculator
        self._middleware_orchestrator = middleware_orchestrator
        self._capability_registry = capability_registry
        self._capability_runtime_mode = capability_runtime_mode

    # ------------------------------------------------------------------
    # Task-view knowledge
    # ------------------------------------------------------------------

    def build_task_view_knowledge(
        self,
        *,
        stage_id: str,
        action_kind: str,
        result: dict[str, object] | None,
        run_id: str,
        stage_summaries: dict[str, StageSummary],
        contract_goal: str,
    ) -> list[str]:
        """Best-effort knowledge extraction for task-view payloads."""
        if self.knowledge_query_fn is None:
            return []
        try:
            run_index = build_run_index(run_id, stage_summaries)
            run_index.current_stage = stage_id
            query_text = self._resolve_knowledge_query_text(
                stage_id=stage_id,
                action_kind=action_kind,
                result=result,
                contract_goal=contract_goal,
            )
            built = build_task_view_with_knowledge_query(
                run_index=run_index,
                stage_summaries=stage_summaries,
                episodes=[],
                query_text=query_text,
                knowledge_query_fn=self.knowledge_query_fn,
                top_k=3,
                budget=12,
            )
            knowledge = built.get("knowledge", [])
            if isinstance(knowledge, list):
                return [str(item) for item in knowledge]
            return []
        except Exception as exc:
            _logger.debug(
                "stage.knowledge_build_failed run_id=%s stage_id=%s error=%s",
                run_id,
                stage_id,
                exc,
            )
            return []

    def _resolve_knowledge_query_text(
        self,
        *,
        stage_id: str,
        action_kind: str,
        result: dict[str, object] | None,
        contract_goal: str,
    ) -> str:
        """Resolve query text for knowledge retrieval hooks."""
        if self.knowledge_query_text_builder is not None:
            return self.knowledge_query_text_builder(
                stage_id, action_kind, result
            )
        return f"{contract_goal} {stage_id} {action_kind}".strip()

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def execute_stage(
        self,
        stage_id: str,
        *,
        # Mutable executor state (passed by reference via the executor)
        executor: Any,
    ) -> str | None:
        """Execute a single stage.

        Returns:
            ``"failed"`` if the stage is a dead end and the run should abort,
            or ``None`` if the stage completed successfully.
        """
        executor.current_stage = stage_id
        self.kernel.open_stage(executor.run_id, stage_id)
        self.kernel.mark_stage_state(executor.run_id, stage_id, StageState.ACTIVE)
        executor._record_event(
            "StageStateChanged",
            {"stage_id": stage_id, "to_state": "active"},
        )
        executor._emit_observability(
            "stage_started",
            {"run_id": executor.run_id, "stage_id": stage_id},
        )
        executor._persist_snapshot(stage_id=stage_id)
        executor._watchdog_reset()

        # --- BudgetGuard: consult tier decision before LLM call ---
        if self.budget_guard is not None:
            is_optional = stage_id in self.optional_stages
            decision = self.budget_guard.decide_tier(
                requested_tier="strong",
                estimated_cost=_ROUTING_ESTIMATED_TOTAL_TOKENS,
                is_optional=is_optional,
            )
            if decision.skipped:
                executor._record_event(
                    "StageSkippedByBudget",
                    {
                        "run_id": executor.run_id,
                        "stage_id": stage_id,
                        "remaining_fraction": self.budget_guard.remaining_fraction,
                    },
                )
                executor._emit_observability(
                    "stage_skipped_budget",
                    {"run_id": executor.run_id, "stage_id": stage_id},
                )
                self.kernel.mark_stage_state(executor.run_id, stage_id, StageState.COMPLETED)
                executor.stage_summaries[stage_id] = StageSummary(
                    stage_id=stage_id,
                    outcome="skipped_by_budget",
                    score=0.0,
                    branch_count=0,
                    selected_branch="",
                    evidence_ids=[],
                )
                return None
            executor._budget_tier_decision = decision
            # Propagate budget fraction into LLM metadata so that
            # TierAwareLLMGateway can apply budget-driven tier downgrade.
            if not hasattr(executor, "_llm_metadata"):
                executor._llm_metadata = {}  # type: ignore[attr-defined]
            executor._llm_metadata["budget_remaining"] = self.budget_guard.remaining_fraction  # type: ignore[attr-defined]

        # --- Auto-compress before routing (lazy compaction) ---
        if self.auto_compress is not None and executor.session is not None:
            try:
                fresh = executor.session.get_records_after_boundary()
                _filtered, summary = self.auto_compress.check_and_compress(
                    fresh, stage_id, budget_tokens=8192
                )
                if summary is not None:
                    executor.session.set_stage_summary(
                        f"{stage_id}_auto", summary
                    )
                    executor.session.mark_compact_boundary(
                        stage_id, summary_ref=f"{stage_id}_auto"
                    )
            except Exception as exc:
                _logger.debug(
                    "stage.auto_compress_failed run_id=%s stage_id=%s error=%s",
                    executor.run_id,
                    stage_id,
                    exc,
                )

        # --- Knowledge retrieval: inject content into ContextManager ---
        if self.retrieval_engine is not None:
            try:
                query = f"{executor.contract.goal} {stage_id}"
                result = self.retrieval_engine.retrieve(query, budget_tokens=800)
                if result.items:
                    # Inject retrieved content so it appears in the LLM context window
                    if self.context_manager is not None and hasattr(
                        self.context_manager, "set_knowledge_context"
                    ):
                        self.context_manager.set_knowledge_context(
                            result.to_context_string()
                        )
                    # Also record the retrieval event in the session (metadata only)
                    if executor.session is not None:
                        executor.session.append_record(
                            "knowledge_retrieved",
                            {
                                "stage_id": stage_id,
                                "items": len(result.items),
                                "tokens": result.total_tokens,
                            },
                            stage_id=stage_id,
                        )
            except Exception as exc:
                _logger.debug(
                    "stage.knowledge_retrieval_failed run_id=%s stage_id=%s error=%s",
                    executor.run_id,
                    stage_id,
                    exc,
                )

        # --- Fix-A: MiddlewareOrchestrator pre_execute lifecycle hook ---
        if self._middleware_orchestrator is not None:
            try:
                mw_pre_result = self._middleware_orchestrator.run(
                    stage_id,
                    {"stage_id": stage_id, "run_id": executor.run_id, "phase": "pre_execute"},
                )
                # Inject perception summary into context if available.
                # The final message payload may carry 'summary' or 'context'
                # from the perception middleware when it is the last stage reached.
                if mw_pre_result is not None:
                    payload = mw_pre_result.payload or {}
                    perception_summary = payload.get("summary") or payload.get("context")
                    if perception_summary and hasattr(executor, "context_manager") and executor.context_manager is not None:
                        if hasattr(executor.context_manager, "set_knowledge_context"):
                            executor.context_manager.set_knowledge_context(perception_summary)
            except Exception as exc:
                _logger.debug(
                    "stage.middleware_pre_execute_failed run_id=%s stage_id=%s error=%s",
                    executor.run_id,
                    stage_id,
                    exc,
                )

        proposals = self.route_engine.propose(
            stage_id, executor.run_id, executor.action_seq
        )
        # Session: record routing LLM call with cost (best-effort)
        if executor.session is not None:
            try:
                from hi_agent.session.run_session import LLMCallRecord
                cost = 0.0
                if self.cost_calculator is not None:
                    cost = self.cost_calculator.calculate(
                        "routing_estimate", _ROUTING_ESTIMATED_INPUT_TOKENS, _ROUTING_ESTIMATED_OUTPUT_TOKENS
                    )
                record = LLMCallRecord(
                    call_id=f"{executor.run_id}:llm:route:{stage_id}",
                    purpose="routing",
                    stage_id=stage_id,
                    model="routing_estimate",
                    input_tokens=_ROUTING_ESTIMATED_INPUT_TOKENS,
                    output_tokens=_ROUTING_ESTIMATED_OUTPUT_TOKENS,
                    cost_usd=cost,
                )
                executor.session.record_llm_call(record)
            except Exception as exc:
                _logger.debug(
                    "stage.llm_call_record_failed run_id=%s stage_id=%s error=%s",
                    executor.run_id,
                    stage_id,
                    exc,
                )
        # BudgetGuard: consume tokens from the routing LLM call
        if self.budget_guard is not None:
            self.budget_guard.consume(_ROUTING_ESTIMATED_TOTAL_TOKENS)
            _bg_tier = (
                executor._budget_tier_decision.tier
                if hasattr(executor, "_budget_tier_decision")
                else "unknown"
            )
            executor._record_event(
                "BudgetGuardTierDecision",
                {
                    "run_id": executor.run_id,
                    "stage_id": stage_id,
                    "tier": _bg_tier,
                    "remaining_fraction": self.budget_guard.remaining_fraction,
                },
            )
        # ContextManager: record LLM response after routing call
        if self.context_manager is not None:
            try:
                self.context_manager.record_response(output_tokens=_ROUTING_ESTIMATED_OUTPUT_TOKENS)
            except Exception as exc:
                _logger.debug(
                    "stage.context_response_record_failed run_id=%s stage_id=%s error=%s",
                    executor.run_id,
                    stage_id,
                    exc,
                )
        # Accumulate artifact_ids produced by all actions in this stage.
        stage_artifact_ids: list[str] = []

        for proposal in proposals:
            # --- CTS / Task budget enforcement ---
            budget_code = executor._check_budget_exceeded(stage_id)
            if budget_code is not None:
                executor._record_event(
                    "BudgetExhausted",
                    {
                        "run_id": executor.run_id,
                        "stage_id": stage_id,
                        "failure_code": budget_code,
                    },
                )
                executor._emit_observability(
                    budget_code,
                    {
                        "run_id": executor.run_id,
                        "stage_id": stage_id,
                        "failure_code": budget_code,
                    },
                )
                break

            # --- Branch lifecycle: open ---
            branch_id = proposal.branch_id
            executor._total_branches_opened += 1
            executor._stage_active_branches[stage_id] = (
                executor._stage_active_branches.get(stage_id, 0) + 1
            )
            self.kernel.open_branch(
                executor.run_id, stage_id, branch_id
            )
            executor._record_event(
                "BranchProposed",
                {
                    "run_id": executor.run_id,
                    "stage_id": stage_id,
                    "branch_id": branch_id,
                    "rationale": proposal.rationale,
                },
            )
            self.kernel.mark_branch_state(
                executor.run_id, stage_id, branch_id, BranchState.ACTIVE
            )
            executor._record_skill_usage_from_proposal(proposal, stage_id)

            # --- Capability availability filter (P1-2b) ---
            if self._capability_registry is not None:
                try:
                    from hi_agent.route_engine.capability_filter import filter_proposal
                    proposal = filter_proposal(
                        proposal,
                        self._capability_registry,
                        self._capability_runtime_mode,
                    )
                except Exception as exc:
                    _logger.warning(
                        "capability_filter raised unexpectedly — proceeding without filter: %s", exc
                    )
                    from hi_agent.observability.fallback import FallbackTaxonomy, record_fallback
                    record_fallback(FallbackTaxonomy.UNEXPECTED_EXCEPTION, "capability_filter", str(exc))
                    # proposal remains unfiltered (existing behavior)

            node = TrajectoryNode(
                node_id=deterministic_id(
                    executor.run_id,
                    stage_id,
                    proposal.branch_id,
                    str(executor.action_seq),
                ),
                node_type=NodeType.ACTION,
                stage_id=stage_id,
                branch_id=proposal.branch_id,
                description=proposal.rationale,
            )
            executor.dag[node.node_id] = node

            success = False
            result: dict | None = None
            try:
                executor._record_event(
                    "ActionDispatched",
                    {
                        "run_id": executor.run_id,
                        "stage_id": stage_id,
                        "branch_id": branch_id,
                        "action_kind": proposal.action_kind,
                    },
                )
                success, result, final_attempt = (
                    executor._execute_action_with_retry(
                        stage_id,
                        proposal,
                        upstream_artifact_ids=list(stage_artifact_ids),
                    )
                )

                # Collect artifact_ids from this action's result.
                if result is not None and isinstance(result, dict):
                    _action_artifacts = result.get("artifact_ids")
                    if isinstance(_action_artifacts, list):
                        stage_artifact_ids.extend(_action_artifacts)

                # --- Fix-D: ToolResultBudget — truncate oversized tool results ---
                if result is not None:
                    try:
                        from hi_agent.task_view.result_budget import (
                            ToolResultBudget,
                            ToolResultBudgetConfig,
                        )
                        _run_ctx = getattr(executor, "run_context", None)
                        _budget_state = (
                            getattr(_run_ctx, "tool_result_budget_state", None)
                            if _run_ctx is not None
                            else None
                        )
                        if _budget_state is not None:
                            _budget = ToolResultBudget(
                                config=ToolResultBudgetConfig(),
                                state=_budget_state,
                            )
                            _raw_content = str(result)
                            _processed = _budget.process(
                                tool_name=str(
                                    getattr(proposal, "action_kind", "unknown")
                                ),
                                result_content=_raw_content,
                            )
                            # If truncated, record the fact in result metadata
                            if _processed != _raw_content:
                                result = dict(result)
                                result["_tool_result_truncated"] = True
                                result["_tool_result_placeholder"] = _processed
                    except Exception as exc:
                        _logger.debug(
                            "stage.tool_result_budget_failed run_id=%s stage_id=%s error=%s",
                            executor.run_id,
                            stage_id,
                            exc,
                        )

                node.local_score = (
                    float(result.get("score", 0.0)) if result else 0.0
                )
                node.propagated_score = node.local_score
                node.state = (
                    NodeState.SUCCEEDED
                    if success
                    else NodeState.FAILED
                )

                if success:
                    executor._record_event(
                        "ActionSucceeded",
                        {
                            "run_id": executor.run_id,
                            "stage_id": stage_id,
                            "branch_id": branch_id,
                            "action_kind": proposal.action_kind,
                        },
                    )
                    acceptance = self.acceptance_policy.evaluate(
                        executor.contract, node
                    )
                    if not acceptance.accepted:
                        node.state = NodeState.FAILED
                        executor._record_event(
                            "AcceptanceRejected",
                            {
                                "stage_id": stage_id,
                                "attempt": final_attempt,
                                "reason": acceptance.reason,
                            },
                        )
                        self.kernel.mark_branch_state(
                            executor.run_id,
                            stage_id,
                            branch_id,
                            BranchState.FAILED,
                            "acceptance_rejected",
                        )
                    else:
                        task_view_id = deterministic_id(
                            executor.run_id,
                            stage_id,
                            proposal.branch_id,
                            str(executor.action_seq),
                            str(
                                result.get(
                                    "evidence_hash", "ev_missing"
                                )
                            ),
                            executor.policy_version,
                        )
                        knowledge_items = (
                            self.build_task_view_knowledge(
                                stage_id=stage_id,
                                action_kind=proposal.action_kind,
                                result=(
                                    result
                                    if isinstance(result, dict)
                                    else None
                                ),
                                run_id=executor.run_id,
                                stage_summaries=executor.stage_summaries,
                                contract_goal=executor.contract.goal,
                            )
                        )
                        tv_id = self.kernel.record_task_view(
                            task_view_id,
                            {
                                "stage_id": stage_id,
                                "action_kind": proposal.action_kind,
                                "local_score": node.local_score,
                                "knowledge": knowledge_items,
                                "policy_versions": {
                                    "route_policy": self.policy_versions.route_policy,
                                    "acceptance_policy": self.policy_versions.acceptance_policy,
                                    "memory_policy": self.policy_versions.memory_policy,
                                    "evaluation_policy": self.policy_versions.evaluation_policy,
                                    "task_view_policy": self.policy_versions.task_view_policy,
                                    "skill_policy": self.policy_versions.skill_policy,
                                },
                            },
                        )
                        decision_ref = executor._make_decision_ref(
                            stage_id, branch_id
                        )
                        self.kernel.bind_task_view_to_decision(
                            tv_id, decision_ref
                        )
                        executor._record_event(
                            "TaskViewRecorded",
                            {
                                "stage_id": stage_id,
                                "attempt": final_attempt,
                                "task_view_id": tv_id,
                                "decision_ref": decision_ref,
                            },
                        )
                        self.kernel.mark_branch_state(
                            executor.run_id,
                            stage_id,
                            branch_id,
                            BranchState.SUCCEEDED,
                        )
                        executor._record_event(
                            "BranchSucceeded",
                            {
                                "run_id": executor.run_id,
                                "stage_id": stage_id,
                                "branch_id": branch_id,
                            },
                        )
                else:
                    # Action failed
                    self.kernel.mark_branch_state(
                        executor.run_id,
                        stage_id,
                        branch_id,
                        BranchState.FAILED,
                        "harness_denied",
                    )
                    executor._record_event(
                        "BranchFailed",
                        {
                            "run_id": executor.run_id,
                            "stage_id": stage_id,
                            "branch_id": branch_id,
                            "failure_code": "harness_denied",
                        },
                    )
            finally:
                # Check human gate triggers after each action
                action_result_for_gate = result if result else {}
                failure_code_for_gate: str | None = None
                if not success:
                    failure_code_for_gate = (
                        action_result_for_gate.get("failure_code")
                        or "harness_denied"
                    )
                    _action_kind = getattr(proposal, "action_kind", "?")
                    _original_error = (
                        action_result_for_gate.get("error_message")
                        or action_result_for_gate.get("error")
                        or failure_code_for_gate
                    )
                    executor._record_failure(
                        failure_code_str=failure_code_for_gate,
                        message=(
                            f"Action {_action_kind} "
                            f"failed at stage {stage_id}"
                        ),
                        stage_id=stage_id,
                        branch_id=branch_id,
                        context={
                            "original_error": str(_original_error),
                            "action_kind": _action_kind,
                            "stage_id": stage_id,
                            "branch_id": branch_id,
                        },
                    )
                executor._check_human_gate_triggers(
                    stage_id, action_result_for_gate, failure_code_for_gate
                )
                executor._watchdog_record_and_check(success, stage_id)
                executor._observe_skill_execution(
                    proposal, stage_id, success,
                    {"action_kind": getattr(proposal, "action_kind", ""),
                     "branch_id": branch_id},
                    result,
                )
                executor.action_seq += 1
                executor.optimizer.backpropagate(node, executor.dag)

        # --- Fix-A: MiddlewareOrchestrator post_execute lifecycle hook ---
        if self._middleware_orchestrator is not None:
            try:
                mw_post_result = self._middleware_orchestrator.run(
                    stage_id,
                    {"stage_id": stage_id, "run_id": executor.run_id, "phase": "post_execute"},
                )
                # Check if evaluation middleware flagged quality issues.
                # The final returned message from the pipeline carries the
                # evaluation payload with 'overall_score' and 'evaluations'.
                if mw_post_result is not None:
                    payload = mw_post_result.payload or {}
                    overall_score = payload.get("overall_score")
                    evaluations = payload.get("evaluations", [])
                    overall_verdict = payload.get("overall_verdict", "pass")
                    if (
                        overall_score is not None
                        and overall_score < 0.5
                        and evaluations
                    ):
                        issues = [
                            e.get("feedback", "")
                            for e in evaluations
                            if e.get("verdict") not in ("pass",)
                        ]
                        if executor.session is not None:
                            executor.session.append_record(
                                "middleware_evaluation",
                                {
                                    "stage_id": stage_id,
                                    "overall_score": overall_score,
                                    "overall_verdict": overall_verdict,
                                    "issues": issues,
                                },
                                stage_id=stage_id,
                            )
                        # Act on verdict: route retry/escalate through recovery
                        # so the restart policy engine applies retry limits.
                        if overall_verdict in ("retry", "escalate"):
                            _logger.info(
                                "stage.eval_verdict_trigger run_id=%s stage_id=%s "
                                "verdict=%s score=%.2f",
                                executor.run_id, stage_id, overall_verdict, overall_score,
                            )
                            self.kernel.mark_stage_state(
                                executor.run_id, stage_id, StageState.FAILED
                            )
                            executor._trigger_recovery(stage_id)
                            _failed_summary = executor._compress_stage_summary(stage_id)
                            _failed_summary.outcome = "failed"  # set at source — compressor doesn't know stage failed
                            _failed_summary.artifact_ids = list(stage_artifact_ids)
                            executor.stage_summaries[stage_id] = _failed_summary
                            executor._persist_snapshot(stage_id=stage_id, result="failed")
                            executor._sync_to_context()
                            return "failed"
            except Exception as exc:
                _logger.debug(
                    "stage.middleware_post_execute_failed run_id=%s stage_id=%s error=%s",
                    executor.run_id,
                    stage_id,
                    exc,
                )

        if detect_dead_end(stage_id, executor.dag):
            self.kernel.mark_stage_state(executor.run_id, stage_id, StageState.FAILED)
            executor._record_event(
                "StageStateChanged",
                {"stage_id": stage_id, "to_state": "failed"},
            )
            executor._trigger_recovery(stage_id)
            _failed_summary = executor._compress_stage_summary(stage_id)
            _failed_summary.outcome = "failed"  # set at source — dead end confirmed, compressor doesn't know
            _failed_summary.artifact_ids = list(stage_artifact_ids)
            executor.stage_summaries[stage_id] = _failed_summary
            executor._persist_snapshot(
                stage_id=stage_id, result="failed"
            )
            executor._signal_run_safe(
                "recovery_failed",
                {"stage_id": stage_id},
            )
            executor._sync_to_context()
            return "failed"

        self.kernel.mark_stage_state(executor.run_id, stage_id, StageState.COMPLETED)
        executor._record_event(
            "StageStateChanged",
            {"stage_id": stage_id, "to_state": "completed"},
        )
        _completed_summary = executor._compress_stage_summary(stage_id)
        _completed_summary.artifact_ids = list(stage_artifact_ids)
        executor.stage_summaries[stage_id] = _completed_summary
        executor._persist_snapshot(stage_id=stage_id)
        executor._emit_observability(
            "stage_completed",
            {"run_id": executor.run_id, "stage_id": stage_id},
        )
        executor._sync_to_context()
        return None  # stage completed OK, continue
