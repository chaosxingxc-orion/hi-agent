"""Run executor for TRACE S1->S5 flow.

This runner now performs real action dispatch through the capability subsystem
and records event/memory artifacts. It is still intentionally compact but no
longer a pure "always success" simulation.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CircuitBreaker,
    register_default_capabilities,
)
from hi_agent.contracts import (
    BranchState,
    NodeState,
    NodeType,
    StageState,
    StageSummary,
    TaskContract,
    TrajectoryNode,
    deterministic_id,
)
from hi_agent.events import EventEmitter, EventEnvelope
from hi_agent.memory import MemoryCompressor, RawEventRecord, RawMemoryStore
from hi_agent.recovery import CompensationHandler, orchestrate_recovery
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.state import RunStateSnapshot, RunStateStore
from hi_agent.task_view.builder import (
    build_run_index,
    build_task_view_with_knowledge_query,
)
from hi_agent.trajectory.dead_end import detect_dead_end
from hi_agent.trajectory.optimizers import GreedyOptimizer
from hi_agent.trajectory.stage_graph import StageGraph, default_trace_stage_graph

STAGES = default_trace_stage_graph().trace_order("S1_understand")


class RunExecutor:
    """Execute TRACE run lifecycle in spike mode."""

    def __init__(
        self,
        contract: TaskContract,
        kernel: RuntimeAdapter,
        *,
        stage_graph: StageGraph | None = None,
        route_engine: Any | None = None,
        knowledge_query_fn: Callable[..., list[object]] | None = None,
        knowledge_query_text_builder: (
            Callable[[str, str, dict[str, object] | None], str] | None
        ) = None,
        action_max_retries: int | None = None,
        runner_role: str | None = None,
        invoker: CapabilityInvoker | None = None,
        event_emitter: EventEmitter | None = None,
        raw_memory: RawMemoryStore | None = None,
        compressor: MemoryCompressor | None = None,
        acceptance_policy: AcceptancePolicy | None = None,
        state_store: RunStateStore | None = None,
        recovery_handlers: Mapping[str, CompensationHandler] | None = None,
        recovery_executor: (
            Callable[
                [tuple[EventEnvelope, ...], Mapping[str, CompensationHandler] | None],
                object,
            ]
            | Callable[[tuple[EventEnvelope, ...]], object]
            | None
        ) = None,
        observability_hook: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        """Initialize run executor state.

        Args:
          contract: Task contract describing user goal.
          kernel: Runtime adapter instance used to track stage states/events.
          stage_graph: Optional stage graph controlling stage traversal order.
          route_engine: Optional route engine with `propose(...)` method.
          knowledge_query_fn: Optional callable used to fetch knowledge snippets.
          knowledge_query_text_builder: Optional query-text builder for stage/action.
          action_max_retries: Maximum retry count for each action.
          runner_role: Optional role propagated to capability invocation.
          invoker: Optional capability invoker. Defaults to built-in registry.
          event_emitter: Optional event emitter for observability.
          raw_memory: Optional L0 memory store.
          compressor: Optional memory compressor.
          acceptance_policy: Optional policy for acceptance decisions.
          state_store: Optional run state persistence store.
          recovery_handlers: Optional action-to-handler map for recovery execution.
          recovery_executor: Optional recovery executor callable.
          observability_hook: Optional best-effort telemetry callback.
        """
        self.contract = contract
        self.kernel = kernel
        # run_id is set during execute() via start_run; keep a fallback for
        # backward compatibility with code that accesses run_id before execute.
        self._run_id_fallback = deterministic_id(contract.task_id, "run")
        self._run_id: str | None = None
        self.stage_graph = stage_graph or default_trace_stage_graph()
        self.optimizer = GreedyOptimizer()
        self.route_engine = self._resolve_route_engine(route_engine)
        self.knowledge_query_fn = knowledge_query_fn
        self.knowledge_query_text_builder = knowledge_query_text_builder
        self.dag: dict[str, TrajectoryNode] = {}
        self.stage_summaries: dict[str, StageSummary] = {}
        self.action_seq = 0
        self.branch_seq = 0
        self.decision_seq = 0
        self.event_emitter = event_emitter or EventEmitter()
        self.raw_memory = raw_memory or RawMemoryStore()
        self.compressor = compressor or MemoryCompressor()
        self.acceptance_policy = acceptance_policy or AcceptancePolicy()
        self.policy_version = "acceptance_v1"
        self.state_store = state_store
        self.recovery_handlers = recovery_handlers
        self.recovery_executor = recovery_executor or orchestrate_recovery
        self.observability_hook = observability_hook
        self._recovery_executor_accepts_handlers = (
            self._supports_optional_handlers_argument(self.recovery_executor)
        )
        self.action_max_retries = self._resolve_action_max_retries(
            action_max_retries, contract.constraints
        )
        self.runner_role = runner_role or self._parse_invoker_role(
            contract.constraints
        )
        self.force_fail_actions = self._parse_forced_fail_actions(
            contract.constraints
        )
        self.invoker = invoker or self._build_default_invoker()
        self._invoker_accepts_role, self._invoker_accepts_metadata = (
            self._supports_optional_invoke_arguments(self.invoker.invoke)
        )
        self.current_stage = ""

    @property
    def run_id(self) -> str:
        """Return the active run ID, falling back to deterministic ID."""
        return self._run_id if self._run_id is not None else self._run_id_fallback

    @run_id.setter
    def run_id(self, value: str) -> None:
        self._run_id = value

    def _make_branch_id(self, stage_id: str) -> str:
        """Generate deterministic branch ID and increment counter."""
        bid = f"{self.run_id}:{stage_id}:b{self.branch_seq:03d}"
        self.branch_seq += 1
        return bid

    def _make_decision_ref(self, stage_id: str, branch_id: str) -> str:
        """Generate deterministic decision reference and increment counter."""
        dref = (
            f"{self.run_id}:{stage_id}:{branch_id}:d{self.decision_seq:03d}"
        )
        self.decision_seq += 1
        return dref

    def _emit_observability(
        self, name: str, payload: dict[str, object]
    ) -> None:
        """Emit one observability callback event without impacting run success."""
        if self.observability_hook is None:
            return
        try:
            self.observability_hook(name, payload)
        except Exception:
            # Telemetry callbacks are best-effort and must never break execution.
            return

    def _resolve_route_engine(self, route_engine: Any | None) -> Any:
        """Return validated route engine instance.

        The runner stays backward compatible by defaulting to `RuleRouteEngine`.
        """
        if route_engine is None:
            return RuleRouteEngine()
        if not hasattr(route_engine, "propose") or not callable(
            route_engine.propose
        ):
            raise TypeError(
                "route_engine must provide callable "
                "propose(stage_id, run_id, seq)"
            )
        return route_engine

    def _resolve_knowledge_query_text(
        self,
        *,
        stage_id: str,
        action_kind: str,
        result: dict[str, object] | None,
    ) -> str:
        """Resolve query text for knowledge retrieval hooks."""
        if self.knowledge_query_text_builder is not None:
            return self.knowledge_query_text_builder(
                stage_id, action_kind, result
            )
        return f"{self.contract.goal} {stage_id} {action_kind}".strip()

    def _build_task_view_knowledge(
        self,
        *,
        stage_id: str,
        action_kind: str,
        result: dict[str, object] | None,
    ) -> list[str]:
        """Best-effort knowledge extraction for task-view payloads."""
        if self.knowledge_query_fn is None:
            return []
        try:
            run_index = build_run_index(self.run_id, self.stage_summaries)
            run_index.current_stage = stage_id
            built = build_task_view_with_knowledge_query(
                run_index=run_index,
                stage_summaries=self.stage_summaries,
                episodes=[],
                query_text=self._resolve_knowledge_query_text(
                    stage_id=stage_id,
                    action_kind=action_kind,
                    result=result,
                ),
                knowledge_query_fn=self.knowledge_query_fn,
                top_k=3,
                budget=12,
            )
            knowledge = built.get("knowledge", [])
            if isinstance(knowledge, list):
                return [str(item) for item in knowledge]
            return []
        except Exception:
            # Knowledge enrichment is optional and must never break execution.
            return []

    def _supports_optional_invoke_arguments(
        self, invoke_callable: object
    ) -> tuple[bool, bool]:
        """Return whether invoker.invoke supports role and metadata arguments."""
        try:
            signature = inspect.signature(invoke_callable)
        except (TypeError, ValueError):
            return False, False

        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True, True

        return (
            "role" in signature.parameters,
            "metadata" in signature.parameters,
        )

    def _supports_optional_handlers_argument(
        self, executor_callable: object
    ) -> bool:
        """Return whether recovery executor supports handlers argument."""
        try:
            signature = inspect.signature(executor_callable)
        except (TypeError, ValueError):
            return False

        positional_count = 0
        for parameter in signature.parameters.values():
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                return True
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                positional_count += 1

        return "handlers" in signature.parameters or positional_count >= 2

    def _invoke_capability(
        self, proposal: object, payload: dict
    ) -> dict:
        """Invoke capability with optional role and action metadata propagation."""
        kwargs: dict[str, object] = {}
        if self._invoker_accepts_role:
            kwargs["role"] = self.runner_role
        if self._invoker_accepts_metadata:
            kwargs["metadata"] = {
                "run_id": self.run_id,
                "stage_id": payload["stage_id"],
                "action_kind": payload["action_kind"],
                "branch_id": payload["branch_id"],
                "seq": payload["seq"],
                "attempt": payload["attempt"],
            }
        if kwargs:
            return self.invoker.invoke(
                proposal.action_kind, payload, **kwargs
            )
        return self.invoker.invoke(proposal.action_kind, payload)

    def _parse_invoker_role(self, constraints: list[str]) -> str | None:
        """Extract invoker role from constraints.

        Supported format: `invoker_role:<role_name>`.
        """
        for item in constraints:
            if not item.startswith("invoker_role:"):
                continue
            role = item.split(":", 1)[1].strip()
            if role:
                return role
        return None

    def _build_default_invoker(self) -> CapabilityInvoker:
        """Build a default capability invoker with built-in action handlers."""
        registry = CapabilityRegistry()
        register_default_capabilities(registry)
        return CapabilityInvoker(registry=registry, breaker=CircuitBreaker())

    def _parse_forced_fail_actions(
        self, constraints: list[str]
    ) -> set[str]:
        """Extract forced-failure action names from constraints.

        Supported format: `fail_action:<action_name>`.
        """
        forced: set[str] = set()
        for item in constraints:
            if not item.startswith("fail_action:"):
                continue
            action_name = item.split(":", 1)[1].strip()
            if action_name:
                forced.add(action_name)
        return forced

    def _parse_action_max_retries(
        self, constraints: list[str]
    ) -> int | None:
        """Extract action retry count from constraints.

        Supported format: `action_max_retries:<non_negative_int>`.
        """
        for item in constraints:
            if not item.startswith("action_max_retries:"):
                continue
            raw_value = item.split(":", 1)[1].strip()
            try:
                return max(0, int(raw_value))
            except ValueError:
                return 0
        return None

    def _resolve_action_max_retries(
        self, configured: int | None, constraints: list[str]
    ) -> int:
        """Resolve action retry count with constructor override precedence."""
        if configured is not None:
            return max(0, configured)

        parsed = self._parse_action_max_retries(constraints)
        if parsed is not None:
            return parsed

        # Keep previous behavior: no retry by default.
        return 0

    def _record_event(self, event_type: str, payload: dict) -> None:
        """Record event to both emitter and raw memory store."""
        self.event_emitter.emit(
            event_type=event_type, run_id=self.run_id, payload=payload
        )
        self.raw_memory.append(
            RawEventRecord(event_type=event_type, payload=payload)
        )

    def _compress_stage_summary(self, stage_id: str) -> StageSummary:
        """Build StageSummary from stage-scoped raw memory records."""
        stage_records = [
            record
            for record in self.raw_memory.list_all()
            if record.payload.get("stage_id") == stage_id
        ]
        compressed = self.compressor.compress_stage(stage_id, stage_records)
        return StageSummary(
            stage_id=stage_id,
            stage_name=stage_id,
            findings=compressed.findings,
            decisions=compressed.decisions,
            outcome=compressed.outcome,
        )

    def _execute_action_with_retry(
        self, stage_id: str, proposal: object
    ) -> tuple[bool, dict | None, int]:
        """Execute one action with retry semantics.

        Returns:
          (success, result_payload_or_none, final_attempt_number)
        """
        max_attempts = self.action_max_retries + 1

        for attempt in range(1, max_attempts + 1):
            payload = {
                "run_id": self.run_id,
                "stage_id": stage_id,
                "branch_id": proposal.branch_id,
                "action_kind": proposal.action_kind,
                "seq": self.action_seq,
                "attempt": attempt,
                "should_fail": proposal.action_kind
                in self.force_fail_actions,
            }
            self._record_event("ActionPlanned", payload)

            try:
                result = self._invoke_capability(proposal, payload)
                success = bool(result.get("success", False))
                self._record_event(
                    "ActionExecuted",
                    {
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "success": success,
                    },
                )
                self._emit_observability(
                    "action_executed",
                    {
                        "run_id": self.run_id,
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "success": success,
                    },
                )
                if success:
                    return True, result, attempt
                if attempt == max_attempts:
                    return False, result, attempt
            except Exception as exc:
                self._record_event(
                    "ActionExecutionFailed",
                    {
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                self._emit_observability(
                    "action_executed",
                    {
                        "run_id": self.run_id,
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "success": False,
                        "error": str(exc),
                    },
                )
                if attempt == max_attempts:
                    return False, None, attempt

        return False, None, max_attempts

    def _persist_snapshot(
        self, *, stage_id: str, result: str | None = None
    ) -> None:
        """Persist current run state when a store is configured."""
        if self.state_store is None:
            return

        stage_states = {
            key: (
                value.value if isinstance(value, StageState) else str(value)
            )
            for key, value in getattr(self.kernel, "stages", {}).items()
        }
        task_views = getattr(self.kernel, "task_views", {})
        snapshot = RunStateSnapshot(
            run_id=self.run_id,
            current_stage=stage_id,
            stage_states=stage_states,
            action_seq=self.action_seq,
            task_views_count=len(task_views),
            result=result,
        )
        self.state_store.save(snapshot)

    def _resolve_recovery_success(self, report: object) -> bool:
        """Extract normalized success flag from recovery report payload."""
        if isinstance(report, dict):
            return bool(report.get("success", True))

        if hasattr(report, "success"):
            return bool(report.success)

        if hasattr(report, "execution_report") and hasattr(
            report.execution_report, "success"
        ):
            return bool(report.execution_report.success)

        return True

    def _resolve_recovery_should_escalate(
        self, report: object
    ) -> bool | None:
        """Extract optional escalation signal from recovery report payload."""
        if isinstance(report, dict) and "should_escalate" in report:
            return bool(report["should_escalate"])

        if hasattr(report, "should_escalate"):
            return bool(report.should_escalate)

        return None

    def _resolve_failed_stage_count(self, report: object) -> int | None:
        """Extract optional failed stage count from recovery report payload."""
        if isinstance(report, dict):
            if "failed_stage_count" in report:
                return int(report["failed_stage_count"])
            failed_stages = report.get("failed_stages")
            if isinstance(failed_stages, list):
                return len(failed_stages)
            return None

        if hasattr(report, "failed_stage_count"):
            return int(report.failed_stage_count)

        if hasattr(report, "failed_stages"):
            failed_stages = report.failed_stages
            if isinstance(failed_stages, list):
                return len(failed_stages)

        return None

    def _trigger_recovery(self, stage_id: str) -> None:
        """Execute recovery hook and emit recovery lifecycle events."""
        self._record_event("RecoveryTriggered", {"stage_id": stage_id})
        consumed_events = tuple(self.event_emitter.events)
        success = False
        report: object | None = None

        try:
            if self._recovery_executor_accepts_handlers:
                report = self.recovery_executor(
                    consumed_events, self.recovery_handlers
                )
            else:
                report = self.recovery_executor(consumed_events)
            success = self._resolve_recovery_success(report)
        except Exception:
            success = False

        payload: dict[str, object] = {
            "stage_id": stage_id,
            "success": success,
        }
        if report is not None:
            should_escalate = self._resolve_recovery_should_escalate(report)
            if should_escalate is not None:
                payload["should_escalate"] = should_escalate
            failed_stage_count = self._resolve_failed_stage_count(report)
            if failed_stage_count is not None:
                payload["failed_stage_count"] = failed_stage_count

        self._record_event(
            "RecoveryCompleted",
            payload,
        )

    def _signal_run_safe(
        self, signal: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Send signal_run to kernel, ignoring errors for robustness."""
        import contextlib

        with contextlib.suppress(Exception):
            self.kernel.signal_run(self.run_id, signal, payload)

    def execute(self) -> str:
        """Execute all stages with deterministic routing and capability dispatch.

        Returns:
          Completion status string (`completed` or `failed`).
        """
        # --- Start run lifecycle via adapter ---
        self._run_id = self.kernel.start_run(self.contract.task_id)
        self._record_event(
            "RunStarted",
            {"run_id": self.run_id, "task_id": self.contract.task_id},
        )

        for stage_id in self.stage_graph.trace_order():
            self.current_stage = stage_id
            self.kernel.open_stage(stage_id)
            self.kernel.mark_stage_state(stage_id, StageState.ACTIVE)
            self._record_event(
                "StageStateChanged",
                {"stage_id": stage_id, "to_state": "active"},
            )
            self._emit_observability(
                "stage_started",
                {"run_id": self.run_id, "stage_id": stage_id},
            )
            self._persist_snapshot(stage_id=stage_id)

            proposals = self.route_engine.propose(
                stage_id, self.run_id, self.action_seq
            )
            for proposal in proposals:
                # --- Branch lifecycle: open ---
                branch_id = self._make_branch_id(stage_id)
                self.kernel.open_branch(
                    self.run_id, stage_id, branch_id
                )
                self._record_event(
                    "BranchProposed",
                    {
                        "run_id": self.run_id,
                        "stage_id": stage_id,
                        "branch_id": branch_id,
                        "rationale": proposal.rationale,
                    },
                )
                self.kernel.mark_branch_state(
                    self.run_id, stage_id, branch_id, BranchState.ACTIVE
                )

                node = TrajectoryNode(
                    node_id=deterministic_id(
                        self.run_id,
                        stage_id,
                        proposal.branch_id,
                        str(self.action_seq),
                    ),
                    node_type=NodeType.ACTION,
                    stage_id=stage_id,
                    branch_id=proposal.branch_id,
                    description=proposal.rationale,
                )
                self.dag[node.node_id] = node

                try:
                    self._record_event(
                        "ActionDispatched",
                        {
                            "run_id": self.run_id,
                            "stage_id": stage_id,
                            "branch_id": branch_id,
                            "action_kind": proposal.action_kind,
                        },
                    )
                    success, result, final_attempt = (
                        self._execute_action_with_retry(stage_id, proposal)
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
                        self._record_event(
                            "ActionSucceeded",
                            {
                                "run_id": self.run_id,
                                "stage_id": stage_id,
                                "branch_id": branch_id,
                                "action_kind": proposal.action_kind,
                            },
                        )
                        acceptance = self.acceptance_policy.evaluate(
                            self.contract, node
                        )
                        if not acceptance.accepted:
                            node.state = NodeState.FAILED
                            self._record_event(
                                "AcceptanceRejected",
                                {
                                    "stage_id": stage_id,
                                    "attempt": final_attempt,
                                    "reason": acceptance.reason,
                                },
                            )
                            # Mark branch as failed after rejection
                            self.kernel.mark_branch_state(
                                self.run_id,
                                stage_id,
                                branch_id,
                                BranchState.FAILED,
                                "acceptance_rejected",
                            )
                        else:
                            task_view_id = deterministic_id(
                                self.run_id,
                                stage_id,
                                proposal.branch_id,
                                str(self.action_seq),
                                str(
                                    result.get(
                                        "evidence_hash", "ev_missing"
                                    )
                                ),
                                self.policy_version,
                            )
                            knowledge_items = (
                                self._build_task_view_knowledge(
                                    stage_id=stage_id,
                                    action_kind=proposal.action_kind,
                                    result=(
                                        result
                                        if isinstance(result, dict)
                                        else None
                                    ),
                                )
                            )
                            tv_id = self.kernel.record_task_view(
                                task_view_id,
                                {
                                    "stage_id": stage_id,
                                    "action_kind": proposal.action_kind,
                                    "local_score": node.local_score,
                                    "knowledge": knowledge_items,
                                },
                            )
                            # Bind task view to decision reference
                            decision_ref = self._make_decision_ref(
                                stage_id, branch_id
                            )
                            self.kernel.bind_task_view_to_decision(
                                tv_id, decision_ref
                            )
                            self._record_event(
                                "TaskViewRecorded",
                                {
                                    "stage_id": stage_id,
                                    "attempt": final_attempt,
                                    "task_view_id": tv_id,
                                    "decision_ref": decision_ref,
                                },
                            )
                            # Mark branch succeeded
                            self.kernel.mark_branch_state(
                                self.run_id,
                                stage_id,
                                branch_id,
                                BranchState.SUCCEEDED,
                            )
                            self._record_event(
                                "BranchSucceeded",
                                {
                                    "run_id": self.run_id,
                                    "stage_id": stage_id,
                                    "branch_id": branch_id,
                                },
                            )
                    else:
                        # Action failed
                        self.kernel.mark_branch_state(
                            self.run_id,
                            stage_id,
                            branch_id,
                            BranchState.FAILED,
                            "harness_denied",
                        )
                        self._record_event(
                            "BranchFailed",
                            {
                                "run_id": self.run_id,
                                "stage_id": stage_id,
                                "branch_id": branch_id,
                                "failure_code": "harness_denied",
                            },
                        )
                finally:
                    self.action_seq += 1
                    self.optimizer.backpropagate(node, self.dag)

            if detect_dead_end(stage_id, self.dag):
                self.kernel.mark_stage_state(stage_id, StageState.FAILED)
                self._record_event(
                    "StageStateChanged",
                    {"stage_id": stage_id, "to_state": "failed"},
                )
                self._trigger_recovery(stage_id)
                self.stage_summaries[stage_id] = (
                    self._compress_stage_summary(stage_id)
                )
                self._persist_snapshot(
                    stage_id=stage_id, result="failed"
                )
                self._signal_run_safe(
                    "recovery_failed",
                    {"stage_id": stage_id},
                )
                self._emit_observability(
                    "run_failed",
                    {"run_id": self.run_id, "stage_id": stage_id},
                )
                return "failed"

            self.kernel.mark_stage_state(stage_id, StageState.COMPLETED)
            self._record_event(
                "StageStateChanged",
                {"stage_id": stage_id, "to_state": "completed"},
            )
            self.stage_summaries[stage_id] = (
                self._compress_stage_summary(stage_id)
            )
            self._persist_snapshot(stage_id=stage_id)
            self._emit_observability(
                "stage_completed",
                {"run_id": self.run_id, "stage_id": stage_id},
            )

        self._persist_snapshot(
            stage_id=self.current_stage, result="completed"
        )
        self._emit_observability(
            "run_completed",
            {"run_id": self.run_id, "stage_id": self.current_stage},
        )
        return "completed"
