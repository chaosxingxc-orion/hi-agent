"""Human gate coordination extracted from RunExecutor (HI-W8-003)."""

from __future__ import annotations

import logging
from typing import Any

from hi_agent.contracts import HumanGateRequest, NodeState
from hi_agent.contracts.requests import RunResult
from hi_agent.gate_protocol import GatePendingError

_logger = logging.getLogger(__name__)


class GateCoordinator:
    """Owns human gate state and delegates execution work to RunExecutor."""

    def __init__(self, executor: Any) -> None:
        self._executor = executor
        self._gate_pending: str | None = None
        self._registered_gates: dict[str, object] = {}

    @property
    def gate_pending(self) -> str | None:
        return self._gate_pending

    @property
    def registered_gates(self) -> dict:
        return self._registered_gates

    def register_gate(
        self,
        gate_id: str,
        gate_type: str = "final_approval",
        phase_name: str = "",
        recommendation: str = "",
        output_summary: str = "",
    ) -> None:
        """Register a named human gate point on this run."""
        from hi_agent.gate_protocol import GateEvent

        executor = self._executor
        event = GateEvent(
            gate_id=gate_id,
            gate_type=gate_type,
            phase_name=phase_name,
            recommendation=recommendation,
            output_summary=output_summary,
        )
        self._registered_gates[gate_id] = event
        self._gate_pending = gate_id

        if executor.session is not None:
            try:
                executor.session.events.append({
                    "event": "gate_registered",
                    "gate_id": gate_id,
                    "gate_type": gate_type,
                    "phase_name": phase_name,
                    "opened_at": event.opened_at,
                })
            except Exception as _exc:  # pragma: no cover
                executor._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.register_gate_session_failed",
                    _exc,
                    run_id=executor.run_id,
                    gate_id=gate_id,
                )

        _logger.info(
            "runner.gate_registered run_id=%s gate_id=%s gate_type=%s phase=%s",
            executor.run_id,
            gate_id,
            gate_type,
            phase_name,
        )

    def resume(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
    ) -> None:
        """Resume execution after a human decision on a registered gate."""
        executor = self._executor
        _logger.info(
            "runner.gate_decision run_id=%s gate_id=%s decision=%s",
            executor.run_id,
            gate_id,
            decision,
        )

        executor._emit_observability("gate_decision", {
            "run_id": executor.run_id,
            "gate_id": gate_id,
            "decision": decision,
            "rationale": rationale,
        })

        if executor.session is not None:
            try:
                executor.session.events.append({
                    "event": "gate_decision",
                    "gate_id": gate_id,
                    "decision": decision,
                    "rationale": rationale,
                })
            except Exception as _exc:  # pragma: no cover
                executor._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.resume_session_failed",
                    _exc,
                    run_id=executor.run_id,
                    gate_id=gate_id,
                )

        if self._gate_pending == gate_id:
            self._gate_pending = None
        if decision == "backtrack":
            executor._run_terminated = True

    def continue_from_gate(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
    ) -> RunResult:
        """Resume execution after a human gate decision."""
        self.resume(gate_id=gate_id, decision=decision, rationale=rationale)
        return self._executor._execute_remaining()

    def continue_from_gate_graph(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
        *,
        last_stage: str | None = None,
        completed_stages: set[str] | None = None,
    ) -> RunResult:
        """Resume graph execution after a human gate decision."""
        executor = self._executor
        self.resume(gate_id=gate_id, decision=decision, rationale=rationale)

        if decision == "backtrack":
            return executor._finalize_run("failed")

        if completed_stages is None:
            if executor.session is not None:
                completed_stages = {
                    sid for sid, state in executor.session.stage_states.items()
                    if state == "completed"
                }
            else:
                completed_stages = set(executor.stage_summaries.keys())

        start_stage = last_stage or executor.current_stage
        if start_stage and start_stage not in completed_stages:
            current_stage: str | None = start_stage
        else:
            successors = (
                executor.stage_graph.successors(start_stage) if start_stage else set()
            )
            candidates = successors - completed_stages
            current_stage = (
                executor._select_next_stage(candidates) if candidates else None
            )

        max_steps = len(executor.stage_graph.transitions) * 2
        steps = 0
        try:
            while current_stage is not None and steps < max_steps:
                steps += 1
                if current_stage in completed_stages:
                    successors = executor.stage_graph.successors(current_stage)
                    candidates = successors - completed_stages
                    current_stage = (
                        executor._select_next_stage(candidates) if candidates else None
                    )
                    continue

                result = executor._execute_stage(current_stage)
                if result == "failed":
                    backtrack = executor.stage_graph.get_backtrack(current_stage)
                    if backtrack and backtrack not in completed_stages:
                        current_stage = backtrack
                        continue
                    handled = executor._handle_stage_failure(current_stage, result)
                    if handled == "failed":
                        return executor._finalize_run("failed")
                completed_stages.add(current_stage)

                successors = executor.stage_graph.successors(current_stage)
                candidates = successors - completed_stages
                if not candidates:
                    break
                if len(candidates) > 1:
                    current_stage = executor._select_next_stage(candidates)
                else:
                    current_stage = next(iter(candidates))
        except GatePendingError:
            raise
        except Exception as exc:
            executor._log_best_effort_exception(
                logging.WARNING, "runner.continue_from_gate_graph_failed", exc,
                run_id=executor.run_id, stage_id=executor.current_stage,
            )
            return executor._finalize_run("failed")

        return executor._finalize_run("completed")

    def _check_human_gate_triggers(
        self,
        stage_id: str,
        action_result: dict,
        failure_code: str | None = None,
    ) -> None:
        """Check if any Human Gate should be auto-triggered."""
        executor = self._executor
        if failure_code == "contradictory_evidence":
            executor.kernel.open_human_gate(
                HumanGateRequest(
                    run_id=executor.run_id,
                    gate_type="contract_correction",
                    gate_ref=executor._make_gate_ref("contract_correction"),
                    context={
                        "stage_id": stage_id,
                        "reason": "Contradictory evidence detected",
                        "failure_code": failure_code,
                    },
                )
            )

        task_budget = executor.contract.budget
        if task_budget is not None and task_budget.max_actions > 0:
            usage_ratio = executor.action_seq / task_budget.max_actions
            if usage_ratio > 0.8:
                has_viable = any(
                    node.state == NodeState.SUCCEEDED
                    for node in executor.dag.values()
                    if node.stage_id == stage_id
                )
                if not has_viable:
                    executor.kernel.open_human_gate(
                        HumanGateRequest(
                            run_id=executor.run_id,
                            gate_type="route_direction",
                            gate_ref=executor._make_gate_ref("route_direction"),
                            context={
                                "stage_id": stage_id,
                                "reason": "Budget nearly exhausted with no viable branch",
                                "budget_usage_ratio": usage_ratio,
                            },
                        )
                    )

        quality_score = action_result.get("quality_score")
        if (
            quality_score is not None
            and quality_score < executor.human_gate_quality_threshold
        ):
            executor.kernel.open_human_gate(
                HumanGateRequest(
                    run_id=executor.run_id,
                    gate_type="artifact_review",
                    gate_ref=executor._make_gate_ref("artifact_review"),
                    context={
                        "stage_id": stage_id,
                        "reason": "Action result quality below threshold",
                        "quality_score": quality_score,
                        "threshold": executor.human_gate_quality_threshold,
                    },
                )
            )

        side_effect_class = action_result.get("side_effect_class")
        if side_effect_class == "irreversible_submit":
            executor.kernel.open_human_gate(
                HumanGateRequest(
                    run_id=executor.run_id,
                    gate_type="final_approval",
                    gate_ref=executor._make_gate_ref("final_approval"),
                    context={
                        "stage_id": stage_id,
                        "reason": "Irreversible action requires approval",
                        "side_effect_class": side_effect_class,
                    },
                )
            )
