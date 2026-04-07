"""Run executor for TRACE S1->S5 flow.

This runner now performs real action dispatch through the capability subsystem
and records event/memory artifacts. It is still intentionally compact but no
longer a pure "always success" simulation.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.evolve.contracts import RunPostmortem
    from hi_agent.evolve.engine import EvolveEngine
    from hi_agent.failures.collector import FailureCollector
    from hi_agent.failures.taxonomy import FailureCode, FailureRecord
    from hi_agent.failures.watchdog import ProgressWatchdog
    from hi_agent.harness.contracts import ActionSpec
    from hi_agent.harness.executor import HarnessExecutor
    from hi_agent.memory.episode_builder import EpisodeBuilder
    from hi_agent.memory.episodic import EpisodicMemoryStore
    from hi_agent.memory.short_term import ShortTermMemoryStore
    from hi_agent.session.run_session import LLMCallRecord, RunSession
    from hi_agent.skill.recorder import SkillUsageRecorder

from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CircuitBreaker,
    register_default_capabilities,
)
from hi_agent.contracts import (
    BranchState,
    CTSExplorationBudget,
    HumanGateRequest,
    NodeState,
    NodeType,
    StageState,
    StageSummary,
    TaskContract,
    TrajectoryNode,
    deterministic_id,
)
from hi_agent.contracts.policy import PolicyVersionSet
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
        cts_budget: CTSExplorationBudget | None = None,
        evolve_engine: EvolveEngine | None = None,
        harness_executor: HarnessExecutor | None = None,
        human_gate_quality_threshold: float = 0.5,
        policy_versions: PolicyVersionSet | None = None,
        failure_collector: FailureCollector | None = None,
        watchdog: ProgressWatchdog | None = None,
        episode_builder: EpisodeBuilder | None = None,
        episodic_store: EpisodicMemoryStore | None = None,
        skill_recorder: SkillUsageRecorder | None = None,
        short_term_store: ShortTermMemoryStore | None = None,
        session: RunSession | None = None,
        retrieval_engine: Any | None = None,  # RetrievalEngine
        knowledge_manager: Any | None = None,  # KnowledgeManager
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
          cts_budget: Optional CTS exploration budget. When provided the
              runner enforces branch limits, action budget (from
              TaskContract.budget), and total branch caps during execution.
          evolve_engine: Optional EvolveEngine for postmortem analysis after
              run completion.
          harness_executor: Optional HarnessExecutor for governed action
              execution. When provided, actions are routed through the
              harness instead of direct capability invocation.
          human_gate_quality_threshold: Quality score threshold below which
              Gate C (artifact_review) is auto-triggered. Defaults to 0.5.
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
        self.cts_budget = cts_budget or CTSExplorationBudget()
        self._total_branches_opened = 0
        self._stage_active_branches: dict[str, int] = {}
        self.evolve_engine = evolve_engine
        self.harness_executor = harness_executor
        self.human_gate_quality_threshold = human_gate_quality_threshold
        self._gate_seq = 0
        self.policy_versions = policy_versions or PolicyVersionSet()

        # --- Final wiring: FailureCollector, Watchdog, Episode, Skill ---
        self.failure_collector = failure_collector
        if self.failure_collector is None:
            try:
                from hi_agent.failures.collector import FailureCollector as _FC
                self.failure_collector = _FC()
            except Exception:
                pass

        self.watchdog = watchdog
        if self.watchdog is None:
            try:
                from hi_agent.failures.watchdog import ProgressWatchdog as _PW
                self.watchdog = _PW()
            except Exception:
                pass

        self.episode_builder = episode_builder
        self.episodic_store = episodic_store
        self.skill_recorder = skill_recorder
        self.short_term_store = short_term_store
        self._skill_ids_used: list[str] = []

        # --- Session: unified state management (additive) ---
        if session is not None:
            self.session = session
        else:
            try:
                from hi_agent.session.run_session import RunSession as _RS
                self.session: RunSession | None = _RS(
                    run_id=self._run_id_fallback,
                    task_contract=contract,
                )
            except Exception:
                self.session = None

        # --- Retrieval engine for knowledge loading ---
        self.retrieval_engine = retrieval_engine

        # --- Knowledge manager for session knowledge ingestion ---
        self.knowledge_manager = knowledge_manager

        # --- Wire session context into route engine (compression pipeline) ---
        self._auto_compress: Any | None = None
        self._cost_calculator: Any | None = None
        if self.session is not None:
            try:
                # 1. Inject context_provider into LLMRouteEngine
                if hasattr(self.route_engine, '_context_provider'):
                    self.route_engine._context_provider = (
                        lambda: self.session.build_context_for_llm("routing")
                    )
                # 2. Create auto-compress trigger
                from hi_agent.task_view.auto_compress import (
                    AutoCompressTrigger as _ACT,
                )
                self._auto_compress = _ACT(compressor=self.compressor)
                # 3. Create cost calculator
                from hi_agent.session.cost_tracker import (
                    CostCalculator as _CC,
                )
                self._cost_calculator = _CC()
            except Exception:
                pass

        # If retrieval_engine available, create enriched context provider
        if self.retrieval_engine is not None and self.session is not None:
            _retrieval = self.retrieval_engine
            _session = self.session
            def _enriched_context():
                ctx = _session.build_context_for_llm("routing")
                try:
                    query = getattr(_session.task_contract, 'goal', '') + " " + _session.current_stage
                    r = _retrieval.retrieve(query.strip(), budget_tokens=500)
                    if r.items:
                        ctx["retrieved_knowledge"] = [i.content[:200] for i in r.items[:3]]
                except Exception:
                    pass
                return ctx
            if hasattr(self.route_engine, '_context_provider'):
                self.route_engine._context_provider = _enriched_context

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
        """Invoke capability with optional role and action metadata propagation.

        When a harness_executor is configured, actions are routed through the
        harness governance pipeline instead of direct capability invocation.
        """
        if self.harness_executor is not None:
            return self._invoke_via_harness(proposal, payload)

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
        # Delegate to session (additive — never break core execution)
        if self.session is not None:
            try:
                self.session.append_record(
                    event_type, payload, stage_id=self.current_stage
                )
                self.session.emit_event(event_type, payload)
            except Exception:
                pass

    def _compress_stage_summary(self, stage_id: str) -> StageSummary:
        """Build StageSummary from stage-scoped raw memory records."""
        stage_records = [
            record
            for record in self.raw_memory.list_all()
            if record.payload.get("stage_id") == stage_id
        ]
        compressed = self.compressor.compress_stage(stage_id, stage_records)
        summary = StageSummary(
            stage_id=stage_id,
            stage_name=stage_id,
            findings=compressed.findings,
            decisions=compressed.decisions,
            outcome=compressed.outcome,
        )
        # Session: store L1 summary and mark compact boundary
        if self.session is not None:
            try:
                self.session.set_stage_summary(stage_id, {
                    "stage_id": stage_id,
                    "findings": compressed.findings,
                    "decisions": compressed.decisions,
                    "outcome": compressed.outcome,
                })
                self.session.mark_compact_boundary(
                    stage_id, summary_ref=stage_id
                )
            except Exception:
                pass
        return summary

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
        # Session checkpoint (independent of state_store)
        if self.session is not None:
            try:
                self.session.current_stage = stage_id
                self.session.stage_states = {
                    key: (
                        value.value if isinstance(value, StageState) else str(value)
                    )
                    for key, value in getattr(self.kernel, "stages", {}).items()
                }
                self.session.action_seq = self.action_seq
                self.session.save_checkpoint()
            except Exception:
                pass

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

    def _make_gate_ref(self, gate_type: str) -> str:
        """Generate a deterministic gate reference."""
        ref = f"{self.run_id}:gate:{gate_type}:{self._gate_seq:03d}"
        self._gate_seq += 1
        return ref

    def _build_postmortem(self, outcome: str) -> RunPostmortem:
        """Build a RunPostmortem from current run state.

        Args:
            outcome: Final outcome string (``completed`` or ``failed``).

        Returns:
            A populated RunPostmortem dataclass.
        """
        from hi_agent.evolve.contracts import RunPostmortem

        stages_completed: list[str] = []
        stages_failed: list[str] = []
        for sid in self.stage_summaries:
            stage_state = self.kernel.stages.get(sid) if hasattr(self.kernel, "stages") else None
            if stage_state == StageState.FAILED:
                stages_failed.append(sid)
            elif stage_state == StageState.COMPLETED:
                stages_completed.append(sid)
            else:
                # Fallback: check summary outcome
                if self.stage_summaries[sid].outcome == "failed":
                    stages_failed.append(sid)
                else:
                    stages_completed.append(sid)

        branches_explored = 0
        branches_pruned = 0
        for node in self.dag.values():
            branches_explored += 1
            if node.state == NodeState.PRUNED:
                branches_pruned += 1

        failure_codes: list[str] = []
        # Prefer structured failure collector when available
        if self.failure_collector is not None:
            try:
                failure_codes = self.failure_collector.get_failure_codes()
            except Exception:
                failure_codes = []
        if not failure_codes:
            for record in self.raw_memory.list_all():
                code = record.payload.get("failure_code")
                if code and code not in failure_codes:
                    failure_codes.append(code)

        return RunPostmortem(
            run_id=self.run_id,
            task_id=self.contract.task_id,
            task_family=self.contract.task_family,
            outcome=outcome,
            stages_completed=stages_completed,
            stages_failed=stages_failed,
            branches_explored=branches_explored,
            branches_pruned=branches_pruned,
            total_actions=self.action_seq,
            failure_codes=failure_codes,
            duration_seconds=0.0,
            policy_versions={
                "route_policy": self.policy_versions.route_policy,
                "acceptance_policy": self.policy_versions.acceptance_policy,
                "memory_policy": self.policy_versions.memory_policy,
                "evaluation_policy": self.policy_versions.evaluation_policy,
                "task_view_policy": self.policy_versions.task_view_policy,
                "skill_policy": self.policy_versions.skill_policy,
            },
        )

    def _invoke_via_harness(
        self, proposal: object, payload: dict
    ) -> dict:
        """Route action through HarnessExecutor and convert result to dict.

        Args:
            proposal: Route proposal with action_kind and branch_id.
            payload: Action payload dict.

        Returns:
            Dict in the format the runner expects from capability invocation.
        """
        from hi_agent.harness.contracts import ActionSpec, ActionState, SideEffectClass

        spec = ActionSpec(
            action_id=deterministic_id(
                self.run_id,
                payload["stage_id"],
                payload["branch_id"],
                str(payload["seq"]),
            ),
            action_type="mutate",
            capability_name=proposal.action_kind,
            payload=payload,
            side_effect_class=SideEffectClass(
                getattr(proposal, "side_effect_class", "read_only")
            )
            if hasattr(proposal, "side_effect_class")
            and proposal.side_effect_class
            in {e.value for e in SideEffectClass}
            else SideEffectClass.READ_ONLY,
        )

        result = self.harness_executor.execute(spec)

        success = result.state == ActionState.SUCCEEDED
        output = result.output if isinstance(result.output, dict) else {}
        return {
            "success": success,
            "score": output.get("score", 0.0),
            "evidence_hash": result.evidence_ref or "ev_missing",
            "action_id": result.action_id,
            "side_effect_class": spec.side_effect_class.value,
            **output,
        }

    def _check_human_gate_triggers(
        self,
        stage_id: str,
        action_result: dict,
        failure_code: str | None = None,
    ) -> None:
        """Check if any Human Gate should be auto-triggered.

        Gate A (contract_correction): contradictory_evidence failure code.
        Gate B (route_direction): budget nearly exhausted (>80%) and no
            viable branch found.
        Gate C (artifact_review): action result quality_score below threshold.
        Gate D (final_approval): irreversible_submit side effect class.
        """
        # Gate A: contradictory evidence
        if failure_code == "contradictory_evidence":
            self.kernel.open_human_gate(
                HumanGateRequest(
                    run_id=self.run_id,
                    gate_type="contract_correction",
                    gate_ref=self._make_gate_ref("contract_correction"),
                    context={
                        "stage_id": stage_id,
                        "reason": "Contradictory evidence detected",
                        "failure_code": failure_code,
                    },
                )
            )

        # Gate B: budget crisis (>80% used and no viable branch)
        task_budget = self.contract.budget
        if task_budget is not None and task_budget.max_actions > 0:
            usage_ratio = self.action_seq / task_budget.max_actions
            if usage_ratio > 0.8:
                # Check if there are any succeeded branches in current stage
                has_viable = any(
                    node.state == NodeState.SUCCEEDED
                    for node in self.dag.values()
                    if node.stage_id == stage_id
                )
                if not has_viable:
                    self.kernel.open_human_gate(
                        HumanGateRequest(
                            run_id=self.run_id,
                            gate_type="route_direction",
                            gate_ref=self._make_gate_ref("route_direction"),
                            context={
                                "stage_id": stage_id,
                                "reason": "Budget nearly exhausted with no viable branch",
                                "budget_usage_ratio": usage_ratio,
                            },
                        )
                    )

        # Gate C: quality threshold
        quality_score = action_result.get("quality_score")
        if quality_score is not None and quality_score < self.human_gate_quality_threshold:
            self.kernel.open_human_gate(
                HumanGateRequest(
                    run_id=self.run_id,
                    gate_type="artifact_review",
                    gate_ref=self._make_gate_ref("artifact_review"),
                    context={
                        "stage_id": stage_id,
                        "reason": "Action result quality below threshold",
                        "quality_score": quality_score,
                        "threshold": self.human_gate_quality_threshold,
                    },
                )
            )

        # Gate D: irreversible action
        side_effect_class = action_result.get("side_effect_class")
        if side_effect_class == "irreversible_submit":
            self.kernel.open_human_gate(
                HumanGateRequest(
                    run_id=self.run_id,
                    gate_type="final_approval",
                    gate_ref=self._make_gate_ref("final_approval"),
                    context={
                        "stage_id": stage_id,
                        "reason": "Irreversible action requires approval",
                        "side_effect_class": side_effect_class,
                    },
                )
            )

    def _check_budget_exceeded(self, stage_id: str) -> str | None:
        """Return a failure code if any CTS or task budget limit is exceeded.

        Returns:
            A standard failure code string, or ``None`` if all budgets
            are within limits.
        """
        # --- Task-level action budget ---
        task_budget = self.contract.budget
        if task_budget is not None and self.action_seq >= task_budget.max_actions:
            return "budget_exhausted"

        # --- CTS branch-per-stage limit ---
        active_in_stage = self._stage_active_branches.get(stage_id, 0)
        if active_in_stage >= self.cts_budget.max_active_branches_per_stage:
            return "budget_exhausted"

        # --- CTS total branches across run ---
        if self._total_branches_opened >= self.cts_budget.max_total_branches_per_run:
            return "budget_exhausted"

        return None

    def _record_failure(
        self,
        failure_code_str: str,
        message: str,
        stage_id: str = "",
        branch_id: str = "",
        action_id: str = "",
        context: dict[str, object] | None = None,
    ) -> None:
        """Record a structured failure to the FailureCollector (best-effort)."""
        if self.failure_collector is None:
            return
        try:
            from hi_agent.failures.taxonomy import FailureCode, FailureRecord

            code = FailureCode(failure_code_str)
            record = FailureRecord(
                failure_code=code,
                message=message,
                run_id=self.run_id,
                stage_id=stage_id,
                branch_id=branch_id,
                action_id=action_id,
                context=context or {},
            )
            self.failure_collector.record(record)
        except Exception:
            pass

    def _watchdog_record_and_check(
        self, success: bool, stage_id: str
    ) -> None:
        """Record action to watchdog and check for no-progress (best-effort).

        If watchdog triggers, records the failure and opens Gate B.
        """
        if self.watchdog is None:
            return
        try:
            self.watchdog.record_action(success=success)
            trigger = self.watchdog.check()
            if trigger is not None:
                # Record to failure collector
                if self.failure_collector is not None:
                    trigger.run_id = self.run_id
                    trigger.stage_id = stage_id
                    self.failure_collector.record(trigger)
                # Trigger Gate B (route_direction)
                self.kernel.open_human_gate(
                    HumanGateRequest(
                        run_id=self.run_id,
                        gate_type="route_direction",
                        gate_ref=self._make_gate_ref("route_direction"),
                        context={
                            "stage_id": stage_id,
                            "reason": trigger.message,
                            "failure_code": "no_progress",
                        },
                    )
                )
        except Exception:
            pass

    def _watchdog_reset(self) -> None:
        """Reset watchdog state at stage transitions (best-effort)."""
        if self.watchdog is None:
            return
        try:
            self.watchdog.reset()
        except Exception:
            pass

    def _record_skill_usage_from_proposal(
        self, proposal: object, stage_id: str
    ) -> None:
        """If proposal has skill_id metadata, record skill usage (best-effort)."""
        if self.skill_recorder is None:
            return
        try:
            skill_id = getattr(proposal, "skill_id", None)
            if skill_id:
                self.skill_recorder.record_usage(
                    skill_id=skill_id, run_id=self.run_id, success=True
                )
                if skill_id not in self._skill_ids_used:
                    self._skill_ids_used.append(skill_id)
        except Exception:
            pass

    def _finalize_skill_outcomes(self, outcome: str) -> None:
        """After run completes, record final outcome per skill used (best-effort)."""
        if self.skill_recorder is None or not self._skill_ids_used:
            return
        try:
            success = outcome == "completed"
            for skill_id in self._skill_ids_used:
                self.skill_recorder.record_usage(
                    skill_id=skill_id, run_id=self.run_id, success=success
                )
        except Exception:
            pass

    def _build_and_store_episode(self, outcome: str) -> None:
        """Build and store episode after run completes (best-effort)."""
        if self.episode_builder is None or self.episodic_store is None:
            return
        try:
            failure_codes: list[str] = []
            if self.failure_collector is not None:
                failure_codes = self.failure_collector.get_failure_codes()

            episode = self.episode_builder.build(
                run_id=self.run_id,
                task_contract=self.contract,
                stage_summaries=self.stage_summaries,
                outcome=outcome,
                failure_codes=failure_codes,
            )
            self.episodic_store.store(episode)
        except Exception:
            pass

    def execute(self) -> str:
        """Execute all stages with deterministic routing and capability dispatch.

        Returns:
          Completion status string (`completed` or `failed`).
        """
        # --- Start run lifecycle via adapter ---
        self._run_id = self.kernel.start_run(self.contract.task_id)
        # Sync session run_id to the kernel-assigned value
        if self.session is not None:
            try:
                self.session.run_id = self._run_id
            except Exception:
                pass
        self._record_event(
            "RunStarted",
            {
                "run_id": self.run_id,
                "task_id": self.contract.task_id,
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
            self._watchdog_reset()

            # --- Auto-compress before routing (lazy compaction) ---
            if self._auto_compress is not None and self.session is not None:
                try:
                    fresh = self.session.get_records_after_boundary()
                    filtered, summary = self._auto_compress.check_and_compress(
                        fresh, stage_id, budget_tokens=8192
                    )
                    if summary is not None:
                        self.session.set_stage_summary(
                            f"{stage_id}_auto", summary
                        )
                        self.session.mark_compact_boundary(
                            stage_id, summary_ref=f"{stage_id}_auto"
                        )
                except Exception:
                    pass

            # --- Knowledge retrieval: inject event into session ---
            if self.retrieval_engine is not None and self.session is not None:
                try:
                    query = f"{self.contract.goal} {stage_id}"
                    result = self.retrieval_engine.retrieve(query, budget_tokens=800)
                    if result.items:
                        self.session.append_record(
                            "knowledge_retrieved",
                            {"stage_id": stage_id, "items": len(result.items),
                             "tokens": result.total_tokens},
                            stage_id=stage_id,
                        )
                except Exception:
                    pass

            proposals = self.route_engine.propose(
                stage_id, self.run_id, self.action_seq
            )
            # Session: record routing LLM call with cost (best-effort)
            if self.session is not None:
                try:
                    from hi_agent.session.run_session import LLMCallRecord
                    cost = 0.0
                    if self._cost_calculator is not None:
                        cost = self._cost_calculator.calculate(
                            "default", 500, 200
                        )
                    record = LLMCallRecord(
                        call_id=f"{self.run_id}:llm:route:{stage_id}",
                        purpose="routing",
                        stage_id=stage_id,
                        model="default",
                        input_tokens=500,
                        output_tokens=200,
                        cost_usd=cost,
                    )
                    self.session.record_llm_call(record)
                except Exception:
                    pass
            for proposal in proposals:
                # --- CTS / Task budget enforcement ---
                budget_code = self._check_budget_exceeded(stage_id)
                if budget_code is not None:
                    self._record_event(
                        "BudgetExhausted",
                        {
                            "run_id": self.run_id,
                            "stage_id": stage_id,
                            "failure_code": budget_code,
                        },
                    )
                    self._emit_observability(
                        "budget_exhausted",
                        {
                            "run_id": self.run_id,
                            "stage_id": stage_id,
                            "failure_code": budget_code,
                        },
                    )
                    break

                # --- Branch lifecycle: open ---
                branch_id = self._make_branch_id(stage_id)
                self._total_branches_opened += 1
                self._stage_active_branches[stage_id] = (
                    self._stage_active_branches.get(stage_id, 0) + 1
                )
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
                self._record_skill_usage_from_proposal(proposal, stage_id)

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

                success = False
                result: dict | None = None
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
                    # Check human gate triggers after each action
                    action_result_for_gate = result if result else {}
                    failure_code_for_gate: str | None = None
                    if not success:
                        failure_code_for_gate = (
                            action_result_for_gate.get("failure_code")
                            or "harness_denied"
                        )
                        # Record structured failure
                        self._record_failure(
                            failure_code_str=failure_code_for_gate,
                            message=f"Action {getattr(proposal, 'action_kind', '?')} failed at stage {stage_id}",
                            stage_id=stage_id,
                            branch_id=branch_id,
                        )
                    self._check_human_gate_triggers(
                        stage_id, action_result_for_gate, failure_code_for_gate
                    )
                    # Watchdog: track action outcome and check for no-progress
                    self._watchdog_record_and_check(success, stage_id)
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
                if self.evolve_engine is not None:
                    postmortem = self._build_postmortem("failed")
                    self.evolve_engine.on_run_completed(postmortem)
                self._finalize_skill_outcomes("failed")
                self._build_and_store_episode("failed")
                # Session: emit cost summary at run end (even on failure)
                if self.session is not None:
                    try:
                        self._emit_observability(
                            "run_cost_summary", self.session.get_cost_summary()
                        )
                    except Exception:
                        pass
                # Build and store short-term memory from session
                if self.short_term_store is not None and self.session is not None:
                    try:
                        stm = self.short_term_store.build_from_session(self.session)
                        self.short_term_store.save(stm)
                        self._emit_observability("short_term_memory_saved", {
                            "run_id": self.run_id,
                            "session_id": stm.session_id,
                            "outcome": stm.outcome,
                        })
                    except Exception:
                        pass
                # Auto-ingest session knowledge
                if self.knowledge_manager is not None and self.session is not None:
                    try:
                        count = self.knowledge_manager.ingest_from_session(self.session)
                        self._emit_observability("knowledge_ingested", {
                            "run_id": self.run_id, "items_ingested": count,
                        })
                    except Exception:
                        pass
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
        if self.evolve_engine is not None:
            postmortem = self._build_postmortem("completed")
            self.evolve_engine.on_run_completed(postmortem)
        self._finalize_skill_outcomes("completed")
        self._build_and_store_episode("completed")
        # Session: emit cost summary at run end
        if self.session is not None:
            try:
                cost = self.session.get_cost_summary()
                cost["run_id"] = self.run_id
                self._emit_observability("run_cost_summary", cost)
            except Exception:
                pass
        # Build and store short-term memory from session
        if self.short_term_store is not None and self.session is not None:
            try:
                stm = self.short_term_store.build_from_session(self.session)
                self.short_term_store.save(stm)
                self._emit_observability("short_term_memory_saved", {
                    "run_id": self.run_id,
                    "session_id": stm.session_id,
                    "outcome": stm.outcome,
                })
            except Exception:
                pass
        # Auto-ingest session knowledge
        if self.knowledge_manager is not None and self.session is not None:
            try:
                count = self.knowledge_manager.ingest_from_session(self.session)
                self._emit_observability("knowledge_ingested", {
                    "run_id": self.run_id, "items_ingested": count,
                })
            except Exception:
                pass
        return "completed"
