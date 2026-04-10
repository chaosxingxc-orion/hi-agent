"""Run executor for TRACE S1->S5 flow.

This runner now performs real action dispatch through the capability subsystem
and records event/memory artifacts. It is still intentionally compact but no
longer a pure "always success" simulation.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.evolve.contracts import RunPostmortem
    from hi_agent.evolve.engine import EvolveEngine
    from hi_agent.failures.collector import FailureCollector
    from hi_agent.failures.watchdog import ProgressWatchdog
    from hi_agent.harness.executor import HarnessExecutor
    from hi_agent.memory.episode_builder import EpisodeBuilder
    from hi_agent.memory.episodic import EpisodicMemoryStore
    from hi_agent.memory.short_term import ShortTermMemoryStore
    from hi_agent.session.run_session import RunSession
    from hi_agent.skill.recorder import SkillUsageRecorder

from datetime import UTC

from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CircuitBreaker,
    register_default_capabilities,
)
from hi_agent.context.run_context import RunContext
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
from hi_agent.runner_lifecycle import RunLifecycle
from hi_agent.runner_stage import StageExecutor
from hi_agent.runner_telemetry import RunTelemetry
from hi_agent.trajectory.dead_end import detect_dead_end
from hi_agent.trajectory.optimizers import GreedyOptimizer
from hi_agent.trajectory.stage_graph import StageGraph, default_trace_stage_graph

STAGES = default_trace_stage_graph().trace_order("S1_understand")
_logger = logging.getLogger(__name__)


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
        skill_observer: Any | None = None,  # SkillObserver
        skill_version_mgr: Any | None = None,  # SkillVersionManager
        skill_loader: Any | None = None,  # SkillLoader
        short_term_store: ShortTermMemoryStore | None = None,
        session: RunSession | None = None,
        retrieval_engine: Any | None = None,  # RetrievalEngine
        knowledge_manager: Any | None = None,  # KnowledgeManager
        context_manager: Any | None = None,  # ContextManager
        run_context: RunContext | None = None,
        budget_guard: Any | None = None,  # BudgetGuard
        optional_stages: set[str] | None = None,
        metrics_collector: Any | None = None,  # MetricsCollector
        memory_lifecycle_manager: Any | None = None,  # MemoryLifecycleManager
        replay_recorder: Any | None = None,  # ReplayRecorder
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
          policy_versions: Optional policy version set recorded in trace data.
          failure_collector: Optional failure collector for structured errors.
          watchdog: Optional progress watchdog for no-progress detection.
          episode_builder: Optional episode builder for episodic memory output.
          episodic_store: Optional episodic memory persistence store.
          skill_recorder: Optional skill usage recorder.
          skill_observer: Optional skill observer sink.
          skill_version_mgr: Optional skill version manager.
          skill_loader: Optional skill loader used for dynamic skill routing.
          short_term_store: Optional short-term memory store.
          session: Optional run session state container.
          retrieval_engine: Optional retrieval engine for memory lookup.
          knowledge_manager: Optional knowledge manager integration.
          context_manager: Optional context manager integration.
          run_context: Optional run context override.
          budget_guard: Optional BudgetGuard for tier decisions per stage.
          optional_stages: Set of stage IDs considered optional (skippable).
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
                from hi_agent.failures.collector import FailureCollector

                self.failure_collector = FailureCollector()
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.failure_collector_init_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=contract.task_id,
                )

        self.watchdog = watchdog
        if self.watchdog is None:
            try:
                from hi_agent.failures.watchdog import ProgressWatchdog

                self.watchdog = ProgressWatchdog()
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.watchdog_init_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=contract.task_id,
                )

        self.episode_builder = episode_builder
        self.episodic_store = episodic_store
        self.skill_recorder = skill_recorder
        self.skill_observer = skill_observer
        self.skill_version_mgr = skill_version_mgr
        self.skill_loader = skill_loader
        self.short_term_store = short_term_store
        self._skill_ids_used: list[str] = []

        # --- Session: unified state management (additive) ---
        if session is not None:
            self.session = session
        else:
            try:
                from hi_agent.session.run_session import RunSession

                self.session: RunSession | None = RunSession(
                    run_id=self._run_id_fallback,
                    task_contract=contract,
                )
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.WARNING,
                    "runner.session_init_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=contract.task_id,
                )
                self.session = None

        # --- Retrieval engine for knowledge loading ---
        self.retrieval_engine = retrieval_engine

        # --- Knowledge manager for session knowledge ingestion ---
        self.knowledge_manager = knowledge_manager

        # --- Context manager: unified context orchestration (additive) ---
        self.context_manager = context_manager

        # --- BudgetGuard: budget-aware tier decisions (additive) ---
        self.budget_guard = budget_guard
        self.optional_stages: set[str] = optional_stages or set()

        # --- MetricsCollector: structured observability (additive) ---
        self.metrics_collector = metrics_collector

        # --- MemoryLifecycleManager: auto dream/consolidation (additive) ---
        self.memory_lifecycle_manager = memory_lifecycle_manager

        # --- ReplayRecorder: optional JSONL event recording (additive) ---
        self.replay_recorder = replay_recorder

        # --- RunContext: per-run state container (additive) ---
        self.run_context = run_context
        if self.run_context is not None:
            # Sync initial state from RunContext
            self.dag = self.run_context.dag
            self.stage_summaries = self.run_context.stage_summaries
            self.action_seq = self.run_context.action_seq
            self.branch_seq = self.run_context.branch_seq
            self.decision_seq = self.run_context.decision_seq
            self.current_stage = self.run_context.current_stage
            self._total_branches_opened = self.run_context.total_branches_opened
            self._stage_active_branches = self.run_context.stage_active_branches
            self._gate_seq = self.run_context.gate_seq
            self._skill_ids_used = self.run_context.skill_ids_used

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
                    AutoCompressTrigger,
                )
                self._auto_compress = AutoCompressTrigger(
                    compressor=self.compressor
                )
                # 3. Create cost calculator
                from hi_agent.session.cost_tracker import (
                    CostCalculator,
                )
                self._cost_calculator = CostCalculator()
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.session_wiring_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=contract.task_id,
                )

        # If retrieval_engine available, create enriched context provider
        if self.retrieval_engine is not None and self.session is not None:
            _retrieval = self.retrieval_engine
            _session = self.session
            def _enriched_context():
                ctx = _session.build_context_for_llm("routing")
                try:
                    query = (
                        getattr(_session.task_contract, "goal", "")
                        + " "
                        + _session.current_stage
                    )
                    r = _retrieval.retrieve(query.strip(), budget_tokens=500)
                    if r.items:
                        ctx["retrieved_knowledge"] = [
                            i.content[:200] for i in r.items[:3]
                        ]
                except Exception as exc:
                    _logger.debug(
                        "runner.routing_context_enrichment_failed run_id=%s stage_id=%s error=%s",
                        _session.run_id,
                        _session.current_stage,
                        exc,
                    )
                return ctx
            if hasattr(self.route_engine, '_context_provider'):
                self.route_engine._context_provider = _enriched_context

        # --- Skill prompt injection into routing context ---
        if self.skill_loader is not None:
            try:
                _skill_loader = self.skill_loader
                _skill_vmgr = self.skill_version_mgr
                _prev_provider = getattr(self.route_engine, '_context_provider', None)

                def _skill_enriched_context() -> dict:
                    ctx: dict = {}
                    if _prev_provider is not None:
                        try:
                            ctx = _prev_provider()
                        except Exception as exc:
                            _logger.debug(
                                "runner.skill_prev_context_failed run_id=%s stage_id=%s error=%s",
                                self.run_id,
                                self.current_stage,
                                exc,
                            )
                            ctx = {}
                    try:
                        prompt = _skill_loader.build_prompt()
                        skill_text = prompt.to_prompt_string()
                        if skill_text:
                            ctx["skill_prompt"] = skill_text
                    except Exception as exc:
                        _logger.debug(
                            "runner.skill_context_enrichment_failed run_id=%s stage_id=%s error=%s",
                            self.run_id,
                            self.current_stage,
                            exc,
                        )
                    return ctx

                if hasattr(self.route_engine, '_context_provider'):
                    self.route_engine._context_provider = _skill_enriched_context
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.skill_context_provider_setup_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=contract.task_id,
                )

        # --- ContextManager: override context provider if provided ---
        if self.context_manager is not None:
            _cm = self.context_manager
            _session_fallback = self.session

            def _managed_context():
                try:
                    snapshot = _cm.prepare_context(
                        purpose="routing",
                        system_prompt=f"TRACE Agent: {contract.goal}",
                    )
                    ctx = snapshot.to_sections_dict()
                    ctx["health"] = snapshot.health.value
                    ctx["utilization_pct"] = snapshot.utilization_pct
                    return ctx
                except Exception as exc:
                    _logger.debug(
                        "runner.context_manager_fallback_failed run_id=%s stage_id=%s error=%s",
                        self.run_id,
                        self.current_stage,
                        exc,
                    )
                    if _session_fallback is not None:
                        return _session_fallback.build_context_for_llm("routing")
                    return {}

            if hasattr(self.route_engine, '_context_provider'):
                self.route_engine._context_provider = _managed_context

        # --- Delegate instances for extracted logic ---
        self._telemetry = RunTelemetry(
            event_emitter=self.event_emitter,
            raw_memory=self.raw_memory,
            observability_hook=self.observability_hook,
            metrics_collector=self.metrics_collector,
            skill_observer=self.skill_observer,
            skill_recorder=self.skill_recorder,
            session=self.session,
            context_manager=self.context_manager,
        )
        self._lifecycle = RunLifecycle(
            session=self.session,
            short_term_store=self.short_term_store,
            knowledge_manager=self.knowledge_manager,
            evolve_engine=self.evolve_engine,
            memory_lifecycle_manager=self.memory_lifecycle_manager,
            budget_guard=self.budget_guard,
            episode_builder=self.episode_builder,
            episodic_store=self.episodic_store,
            failure_collector=self.failure_collector,
            raw_memory=self.raw_memory,
            cts_budget=self.cts_budget,
        )
        self._stage_executor = StageExecutor(
            kernel=self.kernel,
            route_engine=self.route_engine,
            context_manager=self.context_manager,
            budget_guard=self.budget_guard,
            optional_stages=self.optional_stages,
            acceptance_policy=self.acceptance_policy,
            policy_versions=self.policy_versions,
            knowledge_query_fn=self.knowledge_query_fn,
            knowledge_query_text_builder=self.knowledge_query_text_builder,
            retrieval_engine=self.retrieval_engine,
            auto_compress=self._auto_compress,
            cost_calculator=self._cost_calculator,
        )

    @property
    def run_id(self) -> str:
        """Return the active run ID, falling back to deterministic ID."""
        return self._run_id if self._run_id is not None else self._run_id_fallback

    @run_id.setter
    def run_id(self, value: str) -> None:
        """Run run_id."""
        self._run_id = value

    def _sync_to_context(self) -> None:
        """Sync mutable state back to RunContext if present."""
        if self.run_context is None:
            return
        self.run_context.dag = self.dag
        self.run_context.stage_summaries = self.stage_summaries
        self.run_context.action_seq = self.action_seq
        self.run_context.branch_seq = self.branch_seq
        self.run_context.decision_seq = self.decision_seq
        self.run_context.current_stage = self.current_stage
        self.run_context.total_branches_opened = self._total_branches_opened
        self.run_context.stage_active_branches = self._stage_active_branches
        self.run_context.gate_seq = self._gate_seq
        self.run_context.skill_ids_used = self._skill_ids_used

    def _log_best_effort_exception(
        self,
        level: int,
        message: str,
        exc: Exception,
        **context: object,
    ) -> None:
        """Log a best-effort exception without changing control flow."""
        context_bits = " ".join(
            f"{key}={value}"
            for key, value in context.items()
            if value is not None
        )
        if context_bits:
            _logger.log(level, "%s %s error=%s", message, context_bits, exc)
        else:
            _logger.log(level, "%s error=%s", message, exc)

    def _track_llm_cost(self, response: Any, purpose: str = "action") -> None:
        """Record LLM call cost from response if cost tracking is available."""
        if self._cost_calculator is None or self.session is None:
            return
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
            model = getattr(response, "model", "unknown")
            cost = self._cost_calculator.calculate(
                model=model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
            )
            from hi_agent.session.run_session import LLMCallRecord

            record = LLMCallRecord(
                call_id=deterministic_id(self.run_id, model, str(prompt_tokens)),
                purpose=purpose,
                stage_id=self.current_stage or "",
                model=model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                cost_usd=cost,
            )
            self.session.record_llm_call(record)
        except Exception as exc:
            self._log_best_effort_exception(
                logging.DEBUG,
                "runner.llm_cost_tracking_failed",
                exc,
                run_id=self.run_id,
                stage_id=self.current_stage,
            )

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
        self._telemetry.emit_observability(name, payload)

    def _record_metric(
        self, name: str, payload: dict[str, object]
    ) -> None:
        """Translate observability events to structured metric recordings."""
        self._telemetry.record_metric(name, payload)

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
        return self._stage_executor._resolve_knowledge_query_text(
            stage_id=stage_id,
            action_kind=action_kind,
            result=result,
            contract_goal=self.contract.goal,
        )

    def _build_task_view_knowledge(
        self,
        *,
        stage_id: str,
        action_kind: str,
        result: dict[str, object] | None,
    ) -> list[str]:
        """Best-effort knowledge extraction for task-view payloads."""
        return self._stage_executor.build_task_view_knowledge(
            stage_id=stage_id,
            action_kind=action_kind,
            result=result,
            run_id=self.run_id,
            stage_summaries=self.stage_summaries,
            contract_goal=self.contract.goal,
        )

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
        """Record event to both emitter and raw memory store.

        When a :class:`ReplayRecorder` is attached, each event is also
        written to the replay JSONL log.
        """
        self._telemetry.record_event(
            event_type, payload,
            run_id=self.run_id,
            current_stage=self.current_stage,
        )
        if self.replay_recorder is not None:
            # The last emitted envelope is the one we just recorded.
            try:
                latest = self.event_emitter.events[-1]
                self.replay_recorder.record(latest)
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.replay_record_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=self.current_stage,
                )

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
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.stage_summary_persist_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=stage_id,
                )
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
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.session_checkpoint_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=stage_id,
                )

        # ContextManager: emit context health at stage boundaries
        if self.context_manager is not None:
            try:
                report = self.context_manager.get_health_report()
                self._emit_observability("context_health", {
                    "health": report.health.value,
                    "utilization_pct": report.utilization_pct,
                    "compressions": report.compressions_total,
                    "circuit_breaker_open": report.circuit_breaker_open,
                    "diminishing_returns": report.diminishing_returns,
                })
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.context_health_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=stage_id,
                )

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
        except Exception as exc:
            success = False
            self._log_best_effort_exception(
                logging.WARNING,
                "runner.recovery_failed",
                exc,
                run_id=self.run_id,
                stage_id=stage_id,
            )

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
        try:
            self.kernel.signal_run(self.run_id, signal, payload)
        except Exception as exc:
            self._log_best_effort_exception(
                logging.DEBUG,
                "runner.signal_run_failed",
                exc,
                run_id=self.run_id,
                signal=signal,
            )

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
        return self._lifecycle.build_postmortem(
            outcome,
            run_id=self.run_id,
            contract=self.contract,
            stage_summaries=self.stage_summaries,
            dag=self.dag,
            action_seq=self.action_seq,
            policy_versions=self.policy_versions,
            kernel=self.kernel,
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
        return self._lifecycle.check_budget_exceeded(
            stage_id,
            action_seq=self.action_seq,
            contract=self.contract,
            stage_active_branches=self._stage_active_branches,
            total_branches_opened=self._total_branches_opened,
        )

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
        except Exception as exc:
            _logger.warning(
                "failure.record_failed run_id=%s stage_id=%s branch_id=%s action_id=%s error=%s",
                self.run_id,
                stage_id,
                branch_id,
                action_id,
                exc,
            )

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
        except Exception as exc:
            _logger.warning(
                "watchdog.record_or_gate_failed run_id=%s stage_id=%s error=%s",
                self.run_id,
                stage_id,
                exc,
            )

    def _watchdog_reset(self) -> None:
        """Reset watchdog state at stage transitions (best-effort)."""
        if self.watchdog is None:
            return
        try:
            self.watchdog.reset()
        except Exception as exc:
            self._log_best_effort_exception(
                logging.DEBUG,
                "runner.watchdog_reset_failed",
                exc,
                run_id=self.run_id,
                stage_id=self.current_stage,
            )

    def _record_skill_usage_from_proposal(
        self, proposal: object, stage_id: str
    ) -> None:
        """If proposal has skill_id metadata, record skill usage (best-effort)."""
        self._telemetry.record_skill_usage_from_proposal(
            proposal, stage_id,
            run_id=self.run_id,
            skill_ids_used=self._skill_ids_used,
        )

    def _finalize_skill_outcomes(self, outcome: str) -> None:
        """After run completes, record final outcome per skill used (best-effort)."""
        self._telemetry.finalize_skill_outcomes(
            outcome, run_id=self.run_id, skill_ids_used=self._skill_ids_used,
        )

    def _observe_skill_execution(
        self,
        proposal: object,
        stage_id: str,
        action_succeeded: bool,
        payload: dict,
        result: dict | None,
    ) -> None:
        """Record skill execution observation (best-effort, non-blocking)."""
        self._telemetry.observe_skill_execution(
            proposal, stage_id, action_succeeded, payload, result,
            run_id=self.run_id,
            action_seq=self.action_seq,
            task_family=self.contract.task_family,
        )

    def _build_and_store_episode(self, outcome: str) -> None:
        """Build and store episode after run completes (best-effort)."""
        self._lifecycle.build_and_store_episode(
            outcome,
            run_id=self.run_id,
            contract=self.contract,
            stage_summaries=self.stage_summaries,
        )

    def _execute_stage(self, stage_id: str) -> str | None:
        """Execute a single stage.

        Returns:
            ``"failed"`` if the stage is a dead end and the run should abort,
            or ``None`` if the stage completed successfully and execution
            should continue to the next stage.
        """
        return self._stage_executor.execute_stage(stage_id, executor=self)

    def _finalize_run(self, outcome: str) -> str:
        """Run post-execution finalization for a given outcome.

        Handles observability, evolve engine, skill outcomes, episode
        building, cost summary, short-term memory, and knowledge ingestion.

        Returns:
            The *outcome* string unchanged.
        """
        return self._lifecycle.finalize_run(
            outcome,
            run_id=self.run_id,
            current_stage=self.current_stage,
            contract=self.contract,
            stage_summaries=self.stage_summaries,
            dag=self.dag,
            action_seq=self.action_seq,
            policy_versions=self.policy_versions,
            kernel=self.kernel,
            skill_ids_used=self._skill_ids_used,
            emit_observability_fn=self._emit_observability,
            persist_snapshot_fn=self._persist_snapshot,
            finalize_skill_outcomes_fn=self._finalize_skill_outcomes,
            sync_to_context_fn=self._sync_to_context,
        )

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
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.session_run_id_sync_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=self.contract.task_id,
                )
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
        # --- MetricsCollector: mark run as active ---
        if self.metrics_collector is not None:
            try:
                self.metrics_collector.increment("runs_active", 1.0)
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.metrics_increment_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=self.current_stage,
                )

        try:
            for stage_id in self.stage_graph.trace_order():
                stage_result = self._execute_stage(stage_id)
                if stage_result == "failed":
                    return self._finalize_run("failed")
        except Exception as exc:
            self._log_best_effort_exception(
                logging.WARNING,
                "runner.execute_failed",
                exc,
                run_id=self.run_id,
                stage_id=self.current_stage,
            )
            self._record_event("RunError", {"error": str(exc), "run_id": self.run_id})
            return self._finalize_run("failed")

        return self._finalize_run("completed")

    def execute_graph(self) -> str:
        """Execute stages using dynamic graph traversal.

        Instead of pre-computing trace_order(), follows successors()
        dynamically after each stage completes. Uses route_engine to
        choose among multiple successors when available.
        """
        self._run_id = self.kernel.start_run(self.contract.task_id)
        if self.session is not None:
            try:
                self.session.run_id = self._run_id
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.session_run_id_sync_failed",
                    exc,
                    run_id=self.run_id,
                    task_id=self.contract.task_id,
                )
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
        # --- MetricsCollector: mark run as active ---
        if self.metrics_collector is not None:
            try:
                self.metrics_collector.increment("runs_active", 1.0)
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.metrics_increment_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=self.current_stage,
                )

        # Find start stage (zero indegree)
        current_stage = self._find_start_stage()
        completed_stages: set[str] = set()
        max_steps = len(self.stage_graph.transitions) * 2  # safety limit
        steps = 0

        while current_stage is not None and steps < max_steps:
            steps += 1
            result = self._execute_stage(current_stage)
            if result == "failed":
                backtrack = self.stage_graph.get_backtrack(current_stage)
                if backtrack and backtrack not in completed_stages:
                    # Backtrack: re-execute a previous stage
                    current_stage = backtrack
                    continue
                return self._finalize_run("failed")
            completed_stages.add(current_stage)

            # Get next stage from graph
            successors = self.stage_graph.successors(current_stage)
            candidates = successors - completed_stages

            if not candidates:
                # No more stages to run
                break

            if len(candidates) == 1:
                current_stage = next(iter(candidates))
            else:
                # Multiple successors: use route engine or pick lexically
                current_stage = self._select_next_stage(candidates)

        return self._finalize_run("completed")

    def _find_start_stage(self) -> str | None:
        """Find start stage (zero indegree) from stage graph."""
        if not self.stage_graph.transitions:
            return None
        indegree: dict[str, int] = dict.fromkeys(self.stage_graph.transitions, 0)
        for targets in self.stage_graph.transitions.values():
            for t in targets:
                indegree[t] = indegree.get(t, 0) + 1
        roots = sorted(s for s, c in indegree.items() if c == 0)
        return roots[0] if roots else sorted(self.stage_graph.transitions)[0]

    def _select_next_stage(self, candidates: set[str]) -> str:
        """Select next stage from multiple candidates.

        Delegates to route_engine if it has a select_stage method,
        otherwise picks the lexicographically first candidate.
        """
        if hasattr(self.route_engine, "select_stage") and callable(
            self.route_engine.select_stage
        ):
            try:
                return self.route_engine.select_stage(
                    candidates=sorted(candidates),
                    run_id=self.run_id,
                    completed_stages=list(self.stage_summaries.keys()),
                )
            except Exception as exc:
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.select_next_stage_failed",
                    exc,
                    run_id=self.run_id,
                    stage_id=self.current_stage,
                )
        return sorted(candidates)[0]

    def _execute_remaining(self) -> str:
        """Execute stages that haven't been completed yet.

        Skips stages that are already ``completed`` in
        ``session.stage_states``.  Continues from the first
        non-completed stage.

        Returns:
            Completion status string (``completed`` or ``failed``).
        """
        completed_stages: set[str] = set()
        if self.session is not None:
            completed_stages = {
                sid
                for sid, state in self.session.stage_states.items()
                if state == "completed"
            }

        self._emit_observability("run_resumed", {
            "run_id": self.run_id,
            "completed_stages": sorted(completed_stages),
            "resuming_from": self.current_stage,
        })

        all_completed = True
        for stage_id in self.stage_graph.trace_order():
            if stage_id in completed_stages:
                self._emit_observability("stage_skipped_resume", {
                    "run_id": self.run_id, "stage_id": stage_id,
                })
                continue

            all_completed = False
            stage_result = self._execute_stage(stage_id)
            if stage_result == "failed":
                return self._finalize_run("failed")

        if all_completed:
            # All stages were already completed in the checkpoint
            self._emit_observability("run_already_completed", {
                "run_id": self.run_id,
            })

        return self._finalize_run("completed")

    @classmethod
    def resume_from_checkpoint(
        cls,
        checkpoint_path: str,
        kernel: RuntimeAdapter,
        **kwargs: Any,
    ) -> str:
        """Resume a run from a checkpoint file.

        Loads the checkpoint, restores RunSession state (L0, L1,
        stage_states, events, LLM calls, compact boundaries), then
        continues execution from the NEXT incomplete stage.

        Args:
            checkpoint_path: Path to the checkpoint JSON file.
            kernel: RuntimeAdapter instance.
            **kwargs: All other RunExecutor constructor parameters
                (e.g. ``evolve_engine``, ``harness_executor``).

        Returns:
            Completion status string (``completed`` or ``failed``).
        """
        import json as _json

        from hi_agent.session.run_session import RunSession

        # 1. Load checkpoint
        with open(checkpoint_path, encoding="utf-8") as f:
            cp_data = _json.load(f)

        # 2. Reconstruct TaskContract from checkpoint data
        contract_data = cp_data.get("task_contract", {})
        contract = TaskContract(
            task_id=contract_data.get("task_id", cp_data.get("run_id", "resumed")),
            goal=contract_data.get("goal", "resumed task"),
            task_family=contract_data.get("task_family", "quick_task"),
            constraints=contract_data.get("constraints", []),
            acceptance_criteria=contract_data.get("acceptance_criteria", []),
            risk_level=contract_data.get("risk_level", "low"),
        )

        # 3. Restore session from checkpoint
        session = RunSession.from_checkpoint(cp_data, task_contract=contract)

        # 4. Create executor with restored session
        executor = cls(
            contract=contract,
            kernel=kernel,
            session=session,
            **kwargs,
        )

        # 5. Register run with kernel (so kernel tracks it)
        try:
            kernel_run_id = kernel.start_run(contract.task_id)
        except Exception as exc:
            _logger.warning(
                "runner.resume_start_run_failed task_id=%s error=%s",
                contract.task_id,
                exc,
            )
            kernel_run_id = session.run_id

        # 6. Restore internal state from session (override kernel run_id)
        executor._run_id = session.run_id
        executor.action_seq = session.action_seq
        executor.branch_seq = session.branch_seq
        executor.current_stage = session.current_stage

        # Remap the kernel run entry so it knows about the restored run_id
        try:
            if hasattr(kernel, "runs") and kernel_run_id != session.run_id:
                run_data = kernel.runs.pop(kernel_run_id, None)
                if run_data is not None:
                    run_data["run_id"] = session.run_id
                    kernel.runs[session.run_id] = run_data
        except Exception as exc:
            _logger.debug(
                "runner.resume_kernel_remap_failed run_id=%s task_id=%s error=%s",
                session.run_id,
                contract.task_id,
                exc,
            )

        # 7. Restore stage_summaries from session L1
        for stage_id, summary_data in session.l1_summaries.items():
            if stage_id.endswith("_auto"):
                continue  # skip auto-compress summaries
            executor.stage_summaries[stage_id] = StageSummary(
                stage_id=stage_id,
                stage_name=stage_id,
                findings=summary_data.get("findings", []),
                decisions=summary_data.get("decisions", []),
                outcome=summary_data.get("outcome", ""),
            )

        # 8. Execute remaining stages only
        return executor._execute_remaining()


# ---------------------------------------------------------------------------
# Async execution support
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """RunResult class."""
    run_id: str
    success: bool
    completed_nodes: list[str] = field(default_factory=list)


async def execute_async(
    executor: RunExecutor,
    *,
    max_concurrency: int = 64,
) -> RunResult:
    """Execute a RunExecutor using AsyncTaskScheduler and KernelFacade.

    This is a standalone async function (not a method) to avoid mutating
    the existing RunExecutor class interface. Call it as::

        result = await execute_async(executor, max_concurrency=8)
    """
    from hi_agent.task_mgmt.async_scheduler import AsyncTaskScheduler
    from hi_agent.task_mgmt.graph_factory import GraphFactory

    scheduler = AsyncTaskScheduler(
        kernel=executor.kernel, max_concurrency=max_concurrency
    )

    factory = GraphFactory()
    _template_name, graph = factory.auto_select(
        goal=executor.contract.goal,
        task_family=getattr(executor.contract, "task_family", ""),
    )

    run_id = deterministic_id(executor.contract.task_id, "run")
    await executor.kernel.start_run(
        run_id=run_id,
        session_id=run_id,
        metadata={"goal": executor.contract.goal},
    )

    async def make_handler(node_id: str):
        async def handler(action, grant):
            return {"node_id": node_id, "status": "completed"}
        return handler

    schedule_result = await scheduler.run(
        graph=graph,
        run_id=run_id,
        make_handler=make_handler,
    )

    return RunResult(
        run_id=run_id,
        success=schedule_result.success,
        completed_nodes=schedule_result.completed_nodes,
    )
