"""Run executor for TRACE S1->S5 flow.

This runner now performs real action dispatch through the capability subsystem
and records event/memory artifacts. It is still intentionally compact but no
longer a pure "always success" simulation.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

    from hi_agent.contracts.directives import StageDirective
    from hi_agent.evolve.contracts import RunRetrospective
    from hi_agent.evolve.engine import EvolveEngine
    from hi_agent.evolve.feedback_store import FeedbackStore
    from hi_agent.failures.collector import FailureCollector
    from hi_agent.failures.watchdog import ProgressWatchdog
    from hi_agent.harness.executor import HarnessExecutor
    from hi_agent.memory.episode_builder import EpisodeBuilder
    from hi_agent.memory.episodic import EpisodicMemoryStore
    from hi_agent.memory.short_term import ShortTermMemoryStore
    from hi_agent.session.run_session import RunSession
    from hi_agent.skill.recorder import SkillUsageRecorder
    from hi_agent.task_mgmt.delegation import DelegationManager
    from hi_agent.task_mgmt.reflection import ReflectionOrchestrator
    from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine

import time
from datetime import UTC

from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CircuitBreaker,
    register_default_capabilities,
)
from hi_agent.context.run_context import RunContext
from hi_agent.contracts import (
    CTSExplorationBudget,
    HumanGateRequest,
    StageState,
    StageSummary,
    TaskContract,
    TrajectoryNode,
    deterministic_id,
)
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.contracts.requests import RunResult
from hi_agent.events import EventEmitter, EventEnvelope
from hi_agent.execution.action_dispatcher import ActionDispatchContext, ActionDispatcher
from hi_agent.execution.gate_coordinator import GateCoordinator
from hi_agent.execution.recovery_coordinator import (
    RecoveryContext,
    RecoveryCoordinator,
)
from hi_agent.gate_protocol import GatePendingError
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.recovery import CompensationHandler, orchestrate_recovery
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.runner_lifecycle import RunLifecycle
from hi_agent.runner_stage import StageExecutor
from hi_agent.runner_telemetry import RunTelemetry
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.state import RunStateSnapshot, RunStateStore
from hi_agent.trajectory.optimizers import GreedyOptimizer
from hi_agent.trajectory.stage_graph import StageGraph, default_trace_stage_graph

# ---------------------------------------------------------------------------
# Deprecated: STAGES is a sample constant for the TRACE S1-S5 pipeline.
# Business agents that define custom stage graphs should use their own
# stage list.  Import from hi_agent.samples.trace_pipeline.TRACE_STAGES
# for the canonical sample definition.
# ---------------------------------------------------------------------------
STAGES = default_trace_stage_graph().trace_order("S1_understand")
_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-run delegation data types (Task 3 — P2-3)
# ---------------------------------------------------------------------------


@dataclass
class SubRunHandle:
    """Identifies a dispatched child run returned by dispatch_subrun()."""

    subrun_id: str
    agent: str


@dataclass
class SubRunResult:
    """Result of a completed child run returned by await_subrun()."""

    success: bool
    output: str
    error: str | None = None
    gate_id: str | None = None
    status: str = "completed"


def _reflect_task_done_callback(task: Any) -> None:
    """Log completion or failure of an async reflection background task."""
    if task.cancelled():
        _logger.warning("runner.reflect_async_task_cancelled")
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(
            "runner.reflect_async_task_failed error=%s type=%s",
            exc,
            type(exc).__name__,
        )


def _subrun_task_done_callback(task: Any) -> None:
    """Log completion or failure of an async sub-run background task."""
    if task.cancelled():
        _logger.warning("runner.subrun_async_task_cancelled")
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(
            "runner.subrun_async_task_failed error=%s type=%s",
            exc,
            type(exc).__name__,
        )


def _set_engine_context_provider(engine: object, provider: object) -> None:
    """Set context provider on a route engine using the public API when available.

    Falls back to direct attribute assignment for engines that pre-date
    LLMRouteEngine's ``set_context_provider`` method.
    """
    if hasattr(engine, "set_context_provider"):
        engine.set_context_provider(provider)  # type: ignore[union-attr]  expiry_wave: Wave 27
    elif hasattr(engine, "_context_provider"):
        engine._context_provider = provider  # type: ignore[union-attr]  expiry_wave: Wave 27


def _make_subrun_done_callback(
    results_dict: dict[str, object], task_id: str
) -> Callable[[Any], None]:
    """Create a done-callback that stores task-level failures into results_dict."""

    def _cb(task: Any) -> None:
        if task.cancelled():
            _logger.warning("runner.subrun_async_task_cancelled task_id=%s", task_id)
            results_dict[task_id] = SubRunResult(success=False, output="cancelled")
            return
        exc = task.exception()
        if exc is not None:
            _logger.error(
                "runner.subrun_async_task_failed task_id=%s error=%s",
                task_id,
                exc,
            )
            results_dict[task_id] = SubRunResult(success=False, output=f"error: {exc}")
        # If task completed normally, the delegation result is stored by await_subrun
        # via the future's result(), not here.

    return _cb


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
        mid_term_store: Any | None = None,
        long_term_consolidator: Any | None = None,
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
        llm_gateway: Any | None = None,  # LLMGateway — wired into default invoker
        tier_router: Any | None = None,  # TierRouter — passed to lifecycle for P2 feedback
        restart_policy_engine: RestartPolicyEngine | None = None,
        reflection_orchestrator: ReflectionOrchestrator | None = None,
        delegation_manager: DelegationManager | None = None,
        compress_snip_threshold: int | None = None,
        compress_window_threshold: int | None = None,
        compress_compress_threshold: int | None = None,
        replan_hook: Callable[[str, dict], StageDirective | None] | None = None,
        feedback_store: FeedbackStore | None = None,
        evolve_mode: str = "auto",
        # Pre-wired optional components (avoids post-construction mutation in builder)
        middleware_orchestrator: Any | None = None,
        skill_evolver: Any | None = None,
        skill_evolve_interval: int = 10,
        tracer: Any | None = None,
        cancellation_token: Any | None = None,  # CancellationToken | None
        workspace_key: Any | None = None,  # WorkspaceKey — for session storage scoping
        session_storage_dir: str | None = None,  # pre-computed workspace-scoped dir for RunSession
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
          llm_gateway: Optional LLM gateway passed to the default capability
              invoker when *invoker* is not provided.  Enables real model-backed
              execution for all TRACE stage capabilities.
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
        self._workspace_key = workspace_key
        self._session_storage_dir = session_storage_dir
        self.stage_graph = stage_graph or default_trace_stage_graph()
        self.optimizer = GreedyOptimizer()
        self.route_engine = self._resolve_route_engine(route_engine)
        self.knowledge_query_fn = knowledge_query_fn
        self.knowledge_query_text_builder = knowledge_query_text_builder
        self.dag: dict[str, TrajectoryNode] = {}
        self.stage_summaries: dict[str, StageSummary] = {}
        self._capability_provenance_store: dict[str, list[dict]] = {}
        self.action_seq = 0
        self.branch_seq = 0
        self.decision_seq = 0
        if event_emitter is None:
            raise ValueError(
                "Runner.event_emitter must be injected by the builder — "
                "unscoped EventEmitter is not permitted (Rule 6). "
                "Pass event_emitter=EventEmitter() in tests or wire via SystemBuilder."
            )
        self.event_emitter = event_emitter
        if raw_memory is None:
            raise ValueError(
                "Runner.raw_memory must be injected by the builder — "
                "unscoped RawMemoryStore is not permitted (Rule 6). "
                "Check SystemBuilder.build_executor() wiring or pass "
                "raw_memory=RawMemoryStore(...) in tests."
            )
        self.raw_memory = raw_memory
        if compressor is None:
            raise ValueError(
                "Runner.compressor must be injected by the builder — "
                "unscoped MemoryCompressor is not permitted (Rule 6). "
                "Pass compressor=MemoryCompressor() in tests or wire via SystemBuilder."
            )
        self.compressor = compressor
        if acceptance_policy is None:
            raise ValueError(
                "Runner.acceptance_policy must be injected by the builder — "
                "unscoped AcceptancePolicy is not permitted (Rule 6). "
                "Pass acceptance_policy=AcceptancePolicy() in tests or wire via SystemBuilder."
            )
        self.acceptance_policy = acceptance_policy
        self.policy_version = "acceptance_v1"
        self.state_store = state_store
        self.recovery_handlers = recovery_handlers
        self.recovery_executor = recovery_executor or orchestrate_recovery
        self.observability_hook = observability_hook
        self._recovery_executor_accepts_handlers = self._supports_optional_handlers_argument(
            self.recovery_executor
        )
        self.action_max_retries = self._resolve_action_max_retries(
            action_max_retries, contract.constraints
        )
        self.runner_role = runner_role or ActionDispatcher._parse_invoker_role(contract.constraints)
        self.force_fail_actions = self._parse_forced_fail_actions(contract.constraints)
        self.llm_gateway = llm_gateway
        self.invoker = invoker or self._build_default_invoker(llm_gateway)
        self._invoker_accepts_role, self._invoker_accepts_metadata = (
            self._supports_optional_invoke_arguments(self.invoker.invoke)
        )
        self.current_stage = ""
        if cts_budget is None:
            raise ValueError(
                "Runner.cts_budget must be injected by the builder — "
                "unscoped CTSExplorationBudget is not permitted (Rule 6). "
                "Pass cts_budget=CTSExplorationBudget() in tests or wire via SystemBuilder."
            )
        self.cts_budget = cts_budget
        self._total_branches_opened = 0
        self._stage_active_branches: dict[str, int] = {}
        self._compress_snip_threshold = compress_snip_threshold
        self._compress_window_threshold = compress_window_threshold
        self._compress_compress_threshold = compress_compress_threshold
        self._replan_hook = replan_hook
        self._feedback_store = feedback_store
        self._evolve_mode = evolve_mode
        self.evolve_engine = evolve_engine
        self.harness_executor = harness_executor
        self.human_gate_quality_threshold = human_gate_quality_threshold
        self._gate_seq = 0  # RUNTIME-ONLY: per-run counter, valid for instance lifetime
        self.gate_coordinator = GateCoordinator(self)
        # Pending async delegation futures, keyed by task_id.
        self._pending_subrun_futures: dict[str, object] = {}
        # Completed synchronous delegation results, keyed by task_id.
        self._completed_subrun_results: dict[str, object] = {}
        # Pending async reflection background tasks, tracked for cancellation on finalize.
        self._pending_reflection_tasks: list[object] = []
        if policy_versions is None:
            raise ValueError(
                "Runner.policy_versions must be injected by the builder — "
                "unscoped PolicyVersionSet is not permitted (Rule 6). "
                "Pass policy_versions=PolicyVersionSet() in tests or wire via SystemBuilder."
            )
        self.policy_versions = policy_versions

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
        self.mid_term_store = mid_term_store
        self.long_term_consolidator = long_term_consolidator
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
                    storage_dir=self._session_storage_dir,
                    project_id=contract.project_id,
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

        # --- TierRouter: P2 cost-feedback loop ---
        self.tier_router = tier_router

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
                _set_engine_context_provider(
                    self.route_engine,
                    lambda: self.session.build_context_for_llm("routing"),
                )
                # 2. Create auto-compress trigger
                from hi_agent.task_view.auto_compress import (
                    AutoCompressTrigger,
                )

                act_kwargs: dict[str, Any] = {"compressor": self.compressor}
                if self._compress_snip_threshold is not None:
                    act_kwargs["snip_threshold"] = self._compress_snip_threshold
                if self._compress_window_threshold is not None:
                    act_kwargs["window_threshold"] = self._compress_window_threshold
                if self._compress_compress_threshold is not None:
                    act_kwargs["compress_threshold"] = self._compress_compress_threshold
                self._auto_compress = AutoCompressTrigger(**act_kwargs)
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
                        getattr(_session.task_contract, "goal", "") + " " + _session.current_stage
                    )
                    r = _retrieval.retrieve(query.strip(), budget_tokens=500)
                    if r.items:
                        ctx["retrieved_knowledge"] = [i.content[:200] for i in r.items[:3]]
                except Exception as exc:
                    _logger.debug(
                        "runner.routing_context_enrichment_failed run_id=%s stage_id=%s error=%s",
                        _session.run_id,
                        _session.current_stage,
                        exc,
                    )
                return ctx

            _set_engine_context_provider(self.route_engine, _enriched_context)

        # --- Skill prompt injection into routing context ---
        if self.skill_loader is not None:
            try:
                _skill_loader = self.skill_loader
                _prev_provider = getattr(
                    self.route_engine,
                    "context_provider",
                    getattr(self.route_engine, "_context_provider", None),
                )

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

                _set_engine_context_provider(self.route_engine, _skill_enriched_context)
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
                        run_id=self.run_id,
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

            _set_engine_context_provider(self.route_engine, _managed_context)

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
            tracer=tracer,
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
            route_engine=self.route_engine,
            tier_router=self.tier_router,
            evolve_mode=self._evolve_mode,
            skill_evolver=skill_evolver,
            skill_evolve_interval=skill_evolve_interval,
        )
        # Extract capability registry and runtime mode from the invoker
        # (GovernedToolExecutor) so the stage executor can apply the
        # pre-dispatch capability availability filter (P1-2b).
        _cap_registry = getattr(self.invoker, "_registry", None)
        _cap_runtime_mode = getattr(self.invoker, "_runtime_mode", "dev")

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
            middleware_orchestrator=middleware_orchestrator,
            capability_registry=_cap_registry,
            capability_runtime_mode=_cap_runtime_mode,
        )

        # --- Fix-4: ExecutionHookManager — wraps capability invocations so all
        #     registered pre/post hooks fire around every action execution. ---
        try:
            from hi_agent.middleware.hooks import ExecutionHookManager, HookRegistry

            self._hook_registry = HookRegistry()
            self._hook_manager = ExecutionHookManager(self._hook_registry)
        except Exception as _exc:
            _logger.debug(
                "runner.hook_manager_init_failed run_id=%s error=%s",
                self.run_id,
                _exc,
            )
            self._hook_registry = None
            self._hook_manager = None

        # --- Fix-5: NudgeInjector — periodically injects memory/skill nudges
        #     into the agent's context to drive continuous evolution (P1). ---
        try:
            from hi_agent.context.nudge import NudgeConfig, NudgeInjector, NudgeState

            self._nudge_config = NudgeConfig(
                memory_nudge_interval=getattr(
                    getattr(self, "config", None), "memory_nudge_interval", 10
                ),
                skill_nudge_interval=getattr(
                    getattr(self, "config", None), "skill_nudge_interval", 15
                ),
                enabled=getattr(getattr(self, "config", None), "nudge_enabled", True),
            )
            self._nudge_injector = NudgeInjector(self._nudge_config)
            self._nudge_state = NudgeState()
        except Exception as _exc:
            _logger.debug(
                "runner.nudge_injector_init_failed run_id=%s error=%s",
                self.run_id,
                _exc,
            )
            self._nudge_injector = None
            self._nudge_state = None
        # Pending nudge blocks to be prepended to the next task-view payload.
        self._pending_nudge_blocks: list[dict] = []

        # --- RestartPolicyEngine + ReflectionOrchestrator (optional, injected) ---
        self._restart_policy: RestartPolicyEngine | None = restart_policy_engine
        self._reflection_orchestrator: ReflectionOrchestrator | None = reflection_orchestrator
        # Per-stage retry attempt counters used by _handle_stage_failure
        self._stage_attempt: dict[str, int] = {}

        # --- DelegationManager: parallel child-run delegation (optional) ---
        self._delegation_manager: DelegationManager | None = delegation_manager

        # --- CancellationToken: cooperative cancellation at stage boundaries ---
        self._cancellation_token = cancellation_token

    @property
    def run_id(self) -> str:
        """Return the active run ID, falling back to deterministic ID."""
        return self._run_id if self._run_id is not None else self._run_id_fallback

    @run_id.setter
    def run_id(self, value: str) -> None:
        """Run run_id."""
        self._run_id = value

    def _ensure_gate_coordinator(self) -> GateCoordinator:
        coordinator = getattr(self, "gate_coordinator", None)
        if coordinator is None:
            coordinator = GateCoordinator(self)
            self.gate_coordinator = coordinator
        return coordinator

    @property
    def _gate_pending(self) -> str | None:
        return self._ensure_gate_coordinator().gate_pending

    @_gate_pending.setter
    def _gate_pending(self, value: str | None) -> None:
        self._ensure_gate_coordinator()._gate_pending = value

    @property
    def _registered_gates(self) -> dict[str, object]:
        return self._ensure_gate_coordinator().registered_gates

    @_registered_gates.setter
    def _registered_gates(self, value: dict[str, object]) -> None:
        self._ensure_gate_coordinator()._registered_gates = value

    def _sync_to_context(self) -> None:
        """Sync mutable state back to RunContext if present."""
        if self.run_context is None:
            return
        self.run_context.dag = copy.copy(self.dag)
        self.run_context.stage_summaries = copy.copy(self.stage_summaries)
        self.run_context.action_seq = self.action_seq
        self.run_context.branch_seq = self.branch_seq
        self.run_context.decision_seq = self.decision_seq
        self.run_context.current_stage = self.current_stage
        self.run_context.total_branches_opened = self._total_branches_opened
        self.run_context.stage_active_branches = copy.copy(self._stage_active_branches)
        self.run_context.gate_seq = self._gate_seq
        self.run_context.skill_ids_used = copy.copy(self._skill_ids_used)

    def _log_best_effort_exception(
        self,
        level: int,
        message: str,
        exc: Exception,
        **context: object,
    ) -> None:
        """Log a best-effort exception without changing control flow."""
        context_bits = " ".join(
            f"{key}={value}" for key, value in context.items() if value is not None
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

    # ------------------------------------------------------------------
    # Fix-4: ExecutionHookManager helpers
    # ------------------------------------------------------------------

    def _build_action_dispatch_context(self, stage_id: str = "") -> ActionDispatchContext:
        return ActionDispatchContext(
            run_id=self.run_id,
            current_stage=stage_id or self.current_stage,
            action_seq=self.action_seq,
            invoker=self.invoker,
            harness_executor=self.harness_executor,
            runner_role=self.runner_role,
            invoker_accepts_role=self._invoker_accepts_role,
            invoker_accepts_metadata=self._invoker_accepts_metadata,
            hook_manager=self._hook_manager,
            capability_provenance_store=self._capability_provenance_store,
            force_fail_actions=self.force_fail_actions,
            action_max_retries=self.action_max_retries,
            record_event_fn=self._record_event,
            emit_observability_fn=self._emit_observability,
            nudge_check_fn=self._nudge_check_after_action,
        )

    def _invoke_capability_via_hooks(self, proposal: object, payload: dict) -> dict:
        ctx = self._build_action_dispatch_context(payload.get("stage_id", ""))
        return ActionDispatcher(ctx)._invoke_capability_via_hooks(proposal, payload)

    # ------------------------------------------------------------------
    # Fix-5: NudgeInjector helpers
    # ------------------------------------------------------------------

    def _nudge_check_after_action(self, stage_id: str, action_text: str = "") -> None:
        """Check nudge state after an action and accumulate pending blocks.

        Increments the turn counter, optionally resets counters when the
        agent saves memory or creates a skill, and stores any triggered nudge
        blocks in ``self._pending_nudge_blocks`` for injection into the next
        task-view payload.
        """
        if self._nudge_injector is None or self._nudge_state is None:
            return
        try:
            # Reset counters when agent performs the target action
            if action_text:
                from hi_agent.context.nudge import ActionDetector

                memory_saved, skill_created = ActionDetector.detect_from_text(action_text)
                if memory_saved:
                    self._nudge_state.reset_memory()
                if skill_created:
                    self._nudge_state.reset_skill()

            self._nudge_state.increment_turn()
            self._nudge_state.increment_iter()

            triggers = self._nudge_injector.check(self._nudge_state)
            if triggers:
                blocks = [self._nudge_injector.to_system_block(t) for t in triggers]
                self._pending_nudge_blocks.extend(blocks)
                _logger.debug(
                    "runner.nudge_triggered run_id=%s stage_id=%s nudges=%d",
                    self.run_id,
                    stage_id,
                    len(triggers),
                )
        except Exception as exc:
            _logger.debug(
                "runner.nudge_check_failed run_id=%s stage_id=%s error=%s",
                self.run_id,
                stage_id,
                exc,
            )

    def _make_branch_id(self, stage_id: str) -> str:
        """Generate deterministic branch ID and increment counter.

        DEPRECATED: runner_stage.py now uses ``proposal.branch_id`` directly
        so that all events in a single branch execution share the same ID.
        This method is retained for backward compatibility but has no
        remaining callers inside the main execution path.
        """
        bid = f"{self.run_id}:{stage_id}:b{self.branch_seq:03d}"
        self.branch_seq += 1
        return bid

    def _make_decision_ref(self, stage_id: str, branch_id: str) -> str:
        """Generate deterministic decision reference and increment counter."""
        dref = f"{self.run_id}:{stage_id}:{branch_id}:d{self.decision_seq:03d}"
        self.decision_seq += 1
        return dref

    def _emit_observability(self, name: str, payload: dict[str, object]) -> None:
        """Emit one observability callback event without impacting run success."""
        self._telemetry.emit_observability(name, payload)

    def _record_metric(self, name: str, payload: dict[str, object]) -> None:
        """Translate observability events to structured metric recordings."""
        self._telemetry.record_metric(name, payload)

    def _resolve_route_engine(self, route_engine: Any | None) -> Any:
        """Return validated route engine instance.

        The runner stays backward compatible by defaulting to `RuleRouteEngine`.
        """
        if route_engine is None:
            return RuleRouteEngine()
        if not hasattr(route_engine, "propose") or not callable(route_engine.propose):
            raise TypeError("route_engine must provide callable propose(stage_id, run_id, seq)")
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

    def _supports_optional_invoke_arguments(self, invoke_callable: object) -> tuple[bool, bool]:
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

    def _supports_optional_handlers_argument(self, executor_callable: object) -> bool:
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

    def _build_default_invoker(self, llm_gateway: Any | None = None) -> CapabilityInvoker:
        """Build a default capability invoker with built-in action handlers.

        Wraps the real CapabilityInvoker in GovernedToolExecutor so that all
        capability calls flow through the central governance gate.

        Args:
            llm_gateway: Optional LLM gateway for model-backed capability
                execution.  When provided, each default handler calls the LLM
                and falls back to a heuristic on failure.
        """
        import os as _os

        from hi_agent.capability.governance import GovernedToolExecutor
        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm

        registry = CapabilityRegistry()
        register_default_capabilities(registry, llm_gateway=llm_gateway)
        raw_invoker = CapabilityInvoker(
            registry=registry, breaker=CircuitBreaker(), allow_unguarded=True
        )
        _env = _os.environ.get("HI_AGENT_ENV", "dev").lower()
        runtime_mode = _rrm(_env, {})
        return GovernedToolExecutor(
            registry=registry,
            invoker=raw_invoker,
            runtime_mode=runtime_mode,
        )

    def _build_recovery_context(self) -> RecoveryContext:
        """Build context for RecoveryCoordinator."""
        if not hasattr(self, "_pending_reflection_tasks"):
            self._pending_reflection_tasks = []
        if not hasattr(self, "_stage_attempt"):
            self._stage_attempt = {}
        return RecoveryContext(
            event_emitter=getattr(self, "event_emitter", EventEmitter()),
            recovery_executor=getattr(self, "recovery_executor", orchestrate_recovery),
            recovery_handlers=getattr(self, "recovery_handlers", None),
            _recovery_executor_accepts_handlers=getattr(
                self, "_recovery_executor_accepts_handlers", False
            ),
            _record_event=self._record_event,
            _log_best_effort_exception=self._log_best_effort_exception,
            run_id=self.run_id,
            _resolve_failed_stage_count=self._resolve_failed_stage_count,
            _run_terminated=getattr(self, "_run_terminated", False),
            _restart_policy=getattr(self, "_restart_policy", None),
            _stage_attempt=self._stage_attempt,
            contract=self.contract,
            short_term_store=getattr(self, "short_term_store", None),
            context_manager=getattr(self, "context_manager", None),
            _reflection_orchestrator=getattr(self, "_reflection_orchestrator", None),
            _execute_stage=self._execute_stage,
            _get_attempt_history=self._get_attempt_history,
            _pending_reflection_tasks=self._pending_reflection_tasks,
        )

    def _parse_forced_fail_actions(self, constraints: list[str]) -> set[str]:
        """Extract forced-failure action names from constraints.

        Supported format: `fail_action:<action_name>`.
        """
        return RecoveryCoordinator._parse_forced_fail_actions(constraints)

    def _parse_action_max_retries(self, constraints: list[str]) -> int | None:
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

    def _resolve_action_max_retries(self, configured: int | None, constraints: list[str]) -> int:
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
        written to the replay JSONL log.  Each event is also published to
        the process-local EventBus so that SSE subscribers receive live
        updates.
        """
        self._telemetry.record_event(
            event_type,
            payload,
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
        # Publish to SSE EventBus so /events subscribers receive live updates.
        try:
            import datetime as _dt
            import uuid as _uuid

            from hi_agent.runtime_adapter import RuntimeEvent as _RuntimeEvent
            from hi_agent.server.event_bus import event_bus as _event_bus

            _event_bus.publish(
                _RuntimeEvent(
                    run_id=self.run_id or "",
                    event_id=_uuid.uuid4().hex,
                    commit_offset=len(self.event_emitter.events),
                    event_type=event_type,
                    event_class="derived",
                    event_authority="derived_diagnostic",
                    ordering_key=self.current_stage or "",
                    wake_policy="projection_only",
                    created_at=_dt.datetime.now(_dt.UTC).isoformat(),
                    payload_json=dict(payload),
                )
            )
        except Exception as _exc:
            self._log_best_effort_exception(
                logging.DEBUG,
                "runner.event_bus_publish_failed",
                _exc,
                run_id=self.run_id,
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
                self.session.set_stage_summary(
                    stage_id,
                    {
                        "stage_id": stage_id,
                        "findings": compressed.findings,
                        "decisions": compressed.decisions,
                        "outcome": compressed.outcome,
                    },
                )
                self.session.mark_compact_boundary(stage_id, summary_ref=stage_id)
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
        self,
        stage_id: str,
        proposal: object,
        *,
        upstream_artifact_ids: list[str] | None = None,
    ) -> tuple[bool, dict | None, int]:
        ctx = self._build_action_dispatch_context(stage_id)
        dispatcher = ActionDispatcher(ctx)
        return dispatcher._execute_action_with_retry(
            stage_id, proposal, upstream_artifact_ids=upstream_artifact_ids
        )

    def _persist_snapshot(self, *, stage_id: str, result: str | None = None) -> None:
        """Persist current run state when a store is configured."""
        # Session checkpoint (independent of state_store)
        if self.session is not None:
            try:
                self.session.current_stage = stage_id
                self.session.stage_states = {
                    key: (value.value if isinstance(value, StageState) else str(value))
                    for key, value in getattr(self.kernel, "stages", {}).items()
                }
                self.session.action_seq = self.action_seq
                self.session.stage_attempt = dict(self._stage_attempt)
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
                self._emit_observability(
                    "context_health",
                    {
                        "health": report.health.value,
                        "utilization_pct": report.utilization_pct,
                        "compressions": report.compressions_total,
                        "circuit_breaker_open": report.circuit_breaker_open,
                        "diminishing_returns": report.diminishing_returns,
                    },
                )
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
            key: (value.value if isinstance(value, StageState) else str(value))
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
        return RecoveryCoordinator(self._build_recovery_context())._resolve_recovery_success(report)

    def _resolve_recovery_should_escalate(self, report: object) -> bool | None:
        """Extract optional escalation signal from recovery report payload."""
        return RecoveryCoordinator(
            self._build_recovery_context()
        )._resolve_recovery_should_escalate(report)

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
        # Pre-condition guard: check if recovery handlers are configured
        if self.recovery_handlers is None:
            _logger.warning(
                "runner._trigger_recovery no_recovery_handlers_configured stage_id=%s run_id=%s",
                stage_id,
                self.run_id,
            )

        # Build recovery context with exception context propagation
        try:
            ctx = self._build_recovery_context()
        except Exception as exc:
            raise RuntimeError(f"recovery context build failed for stage {stage_id!r}") from exc

        return RecoveryCoordinator(ctx)._trigger_recovery(stage_id)

    def _signal_run_safe(self, signal: str, payload: dict[str, Any] | None = None) -> None:
        """Send signal_run to kernel, ignoring errors for robustness."""
        try:
            result = self.kernel.signal_run(self.run_id, signal, payload)
            # If kernel.signal_run is a coroutine (async facade), close it
            # gracefully rather than letting Python emit an "unawaited coroutine"
            # RuntimeWarning.
            if inspect.iscoroutine(result):
                result.close()
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

    def _build_postmortem(self, outcome: str) -> RunRetrospective:
        """Build a RunRetrospective from current run state.

        Args:
            outcome: Final outcome string (``completed`` or ``failed``).

        Returns:
            A populated RunRetrospective dataclass.
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

    def _invoke_via_harness(self, proposal: object, payload: dict) -> dict:
        ctx = self._build_action_dispatch_context(payload.get("stage_id", ""))
        return ActionDispatcher(ctx)._invoke_via_harness(proposal, payload)

    def _check_human_gate_triggers(
        self,
        stage_id: str,
        action_result: dict,
        failure_code: str | None = None,
    ) -> None:
        """Check if any Human Gate should be auto-triggered."""
        return self.gate_coordinator._check_human_gate_triggers(
            stage_id=stage_id,
            action_result=action_result,
            failure_code=failure_code,
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

    def _watchdog_record_and_check(self, success: bool, stage_id: str) -> None:
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
                        tenant_id=getattr(self, "tenant_id", ""),
                        user_id=getattr(self, "user_id", ""),
                        session_id=getattr(self, "session_id", ""),
                        project_id=getattr(self.contract, "project_id", ""),
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

    def _record_skill_usage_from_proposal(self, proposal: object, stage_id: str) -> None:
        """If proposal has skill_id metadata, record skill usage (best-effort)."""
        self._telemetry.record_skill_usage_from_proposal(
            proposal,
            stage_id,
            run_id=self.run_id,
            skill_ids_used=self._skill_ids_used,
        )

    def _finalize_skill_outcomes(self, outcome: str) -> None:
        """After run completes, record final outcome per skill used (best-effort)."""
        self._telemetry.finalize_skill_outcomes(
            outcome,
            run_id=self.run_id,
            skill_ids_used=self._skill_ids_used,
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
            proposal,
            stage_id,
            action_succeeded,
            payload,
            result,
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

        Raises:
            GatePendingError: If a human gate is pending. Call
                :meth:`resume` with the blocking gate_id before continuing.
        """
        # Backtrack guard: honour a human reviewer's decision to abort the run.
        if getattr(self, "_run_terminated", False):
            _logger.info(
                "runner.stage_skipped_terminated stage_id=%s run_id=%s",
                stage_id,
                self.run_id,
            )
            return "failed"
        # Human gate enforcement: block stage execution while a gate is pending.
        if self._gate_pending is not None:
            raise GatePendingError(gate_id=self._gate_pending)
        # Deadline enforcement: fail fast rather than burning budget past the deadline.
        if self.contract.deadline:
            try:
                from datetime import datetime

                dl = datetime.fromisoformat(self.contract.deadline.replace("Z", "+00:00"))
                if datetime.now(UTC) >= dl:
                    self._record_failure(
                        "execution_budget_exhausted",
                        f"Task deadline exceeded: {self.contract.deadline}",
                        stage_id=stage_id,
                    )
                    _logger.warning(
                        "runner.deadline_exceeded run_id=%s stage_id=%s deadline=%s",
                        self.run_id,
                        stage_id,
                        self.contract.deadline,
                    )
                    return "failed"
            except (ValueError, TypeError):
                pass  # malformed deadline string — ignore rather than crash
        if self._cancellation_token is not None:
            self._cancellation_token.check_or_raise()
        return self._stage_executor.execute_stage(stage_id, executor=self)

    def _build_finalizer_context(self):
        from hi_agent.execution.run_finalizer import RunFinalizerContext

        return RunFinalizerContext(
            run_id=self.run_id,
            tenant_id=getattr(self, "tenant_id", "") or getattr(self, "_tenant_id", "") or "",
            contract=self.contract,
            lifecycle=self._lifecycle,
            kernel=self.kernel,
            stage_summaries=self.stage_summaries,
            current_stage=getattr(self, "current_stage", None),
            dag=getattr(self, "dag", None),
            action_seq=getattr(self, "action_seq", None),
            policy_versions=getattr(self, "policy_versions", None),
            raw_memory=getattr(self, "raw_memory", None),
            mid_term_store=getattr(self, "mid_term_store", None),
            long_term_consolidator=getattr(self, "long_term_consolidator", None),
            failure_collector=getattr(self, "failure_collector", None),
            feedback_store=getattr(self, "_feedback_store", None),
            restart_policy=getattr(self, "_restart_policy", None),
            last_exception_msg=getattr(self, "_last_exception_msg", None),
            last_exception_type=getattr(self, "_last_exception_type", None),
            skill_ids_used=getattr(self, "_skill_ids_used", []),
            run_start_monotonic=getattr(self, "_run_start_monotonic", None),
            capability_provenance_store=getattr(self, "_capability_provenance_store", {}),
            pending_subrun_futures=getattr(self, "_pending_subrun_futures", {}),
            completed_subrun_results=getattr(self, "_completed_subrun_results", {}),
            emit_observability_fn=getattr(self, "_emit_observability", None),
            persist_snapshot_fn=getattr(self, "_persist_snapshot", None),
            finalize_skill_outcomes_fn=getattr(self, "_finalize_skill_outcomes", None),
            sync_to_context_fn=getattr(self, "_sync_to_context", None),
            env=getattr(self, "_env", "dev"),
            readiness_snapshot=getattr(self, "_readiness_snapshot", {}),
            mcp_status=getattr(self, "_mcp_status", {}),
            stages=getattr(self, "_stages", []),
        )

    def _cancel_pending_subruns(self, status: str) -> None:
        """Cancel orphaned sub-run futures and reflection tasks.

        Delegates to RunFinalizer._cancel_pending_subruns (HI-W7-004).
        Kept here so callers that reference this method directly still work.
        """
        from hi_agent.execution.run_finalizer import RunFinalizer

        RunFinalizer(self._build_finalizer_context())._cancel_pending_subruns(status)

    async def _reap_pending_subruns(self, timeout: float = 5.0) -> None:
        """Cancel and await all pending subrun futures within *timeout* seconds.

        The synchronous _cancel_pending_subruns() only calls future.cancel()
        without awaiting, so tasks leak until GC.  This async variant drives
        each cancelled future to completion (or timeout) so the event loop
        can release associated resources promptly on runner shutdown.

        Args:
            timeout: Per-future wall-clock seconds before abandoning the await.
        """
        import contextlib

        for _task_id, fut in list(self._pending_subrun_futures.items()):
            if callable(getattr(fut, "done", None)) and not fut.done():
                fut.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        self._pending_subrun_futures.clear()

    def _finalize_run(self, outcome: str) -> RunResult:
        """Delegate finalization to RunFinalizer (HI-W7-004)."""
        from hi_agent.execution.run_finalizer import RunFinalizer

        return RunFinalizer(self._build_finalizer_context()).finalize(outcome)

    def _build_stage_orchestrator_context(self):
        """Build context for StageOrchestrator (HI-W10-001)."""
        from hi_agent.execution.stage_orchestrator import StageOrchestratorContext

        return StageOrchestratorContext(
            run_id=self.run_id,
            contract=self.contract,
            stage_graph=self.stage_graph,
            stage_summaries=self.stage_summaries,
            policy_versions=self.policy_versions,
            session=self.session,
            route_engine=self.route_engine,
            metrics_collector=self.metrics_collector,
            replan_hook=getattr(self, "_replan_hook", None),
            execute_stage_fn=self._execute_stage,
            handle_stage_failure_fn=self._handle_stage_failure,
            finalize_run_fn=self._finalize_run,
            emit_observability_fn=self._emit_observability,
            log_best_effort_fn=self._log_best_effort_exception,
            record_event_fn=self._record_event,
            set_executor_attr_fn=lambda k, v: setattr(self, k, v),
        )

    def execute(self) -> RunResult:
        """Execute all stages with deterministic routing and capability dispatch.

        Returns:
          A structured :class:`~hi_agent.contracts.requests.RunResult`.
          For backward compatibility, ``str(result)`` returns the status string
          (``"completed"`` or ``"failed"``).
        """
        from hi_agent.execution.stage_orchestrator import StageOrchestrator
        from hi_agent.observability.fallback import clear_fallback_events

        self._run_id = self.kernel.start_run(self.contract.task_id)
        clear_fallback_events(self._run_id)
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
        return StageOrchestrator(self._build_stage_orchestrator_context()).run_linear()

    def execute_graph(self) -> RunResult:
        """Execute stages using dynamic graph traversal.

        Instead of pre-computing trace_order(), follows successors()
        dynamically after each stage completes. Uses route_engine to
        choose among multiple successors when available.
        """
        from hi_agent.execution.stage_orchestrator import StageOrchestrator
        from hi_agent.observability.fallback import clear_fallback_events

        self._run_id = self.kernel.start_run(self.contract.task_id)
        clear_fallback_events(self._run_id)
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
        return StageOrchestrator(self._build_stage_orchestrator_context()).run_graph()

    def _handle_stage_failure(
        self,
        stage_id: str,
        stage_result: str,
        *,
        max_retries: int = 3,
    ) -> str:
        """Decide how to handle a stage failure using RestartPolicyEngine.

        When no RestartPolicyEngine is configured the method returns "failed"
        immediately, preserving the original behaviour.  When an engine is
        present it queries ``engine.decide(...)`` and acts on the decision:

        * retry   — re-execute the stage (up to *max_retries* times)
        * reflect — run ReflectionOrchestrator then continue
        * escalate — log the escalation and return "failed"
        * abort   — return "failed" immediately

        All new logic is wrapped in try/except so any error falls back to the
        original "failed" path.
        """
        return RecoveryCoordinator(self._build_recovery_context())._handle_stage_failure(
            stage_id,
            stage_result,
            max_retries=max_retries,
        )

    def _get_attempt_history(self, stage_id: str) -> list:
        """Return prior attempt records for the given stage_id.

        DF-18 / A-37 (Rule 5 error-visibility): a bare ``except Exception``
        here made "no prior attempts" indistinguishable from "retrieval
        failed" — the restart policy then drives retry decisions from a
        silently-empty history. Narrow to the expected missing-attribute
        shape (when the restart policy backend has no per-task record yet)
        and surface anything else through a WARNING log before returning
        an empty list.
        """
        try:
            all_attempts = self._restart_policy._get_attempts(self.contract.task_id)
            return [a for a in all_attempts if getattr(a, "stage_id", None) == stage_id]
        except (AttributeError, KeyError):
            # Expected when the restart policy backend has no entry yet.
            return []
        except Exception as exc:
            _logger.warning(
                "runner.attempt_history_lookup_failed task_id=%s stage_id=%s error=%s",
                self.contract.task_id,
                stage_id,
                exc,
            )
            return []

    def _find_start_stage(self) -> str | None:
        """Find start stage — delegates to StageOrchestrator (HI-W10-001)."""
        from hi_agent.execution.stage_orchestrator import StageOrchestrator

        return StageOrchestrator(self._build_stage_orchestrator_context())._find_start_stage()

    def _select_next_stage(self, candidates: set[str]) -> str:
        """Select next stage — delegates to StageOrchestrator (HI-W10-001)."""
        from hi_agent.execution.stage_orchestrator import StageOrchestrator

        return StageOrchestrator(self._build_stage_orchestrator_context())._select_next_stage(
            candidates
        )

    def _execute_remaining(self) -> RunResult:
        """Execute remaining stages via StageOrchestrator (HI-W10-001)."""
        from hi_agent.execution.stage_orchestrator import StageOrchestrator

        return StageOrchestrator(self._build_stage_orchestrator_context()).run_resume()

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
            profile_id=contract_data.get("profile_id", ""),  # J5-3: restore profile scoping
            project_id=contract_data.get("project_id", ""),  # P1.4: restore project scoping
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
        executor._stage_attempt = dict(session.stage_attempt)

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

        # 8. Reconstruct raw_memory so L0 events from resumed stages are appended.
        try:
            import os as _os

            _resume_pid = getattr(contract, "profile_id", "") or ""
            _default_base = _os.path.join(".episodes", _resume_pid) if _resume_pid else ".episodes"
            base_dir = kwargs.get("raw_memory_base_dir", _default_base)
            executor.raw_memory = RawMemoryStore(
                run_id=session.run_id,
                base_dir=base_dir,
            )
        except Exception as _rm_exc:
            _logger.debug(
                "runner.resume_raw_memory_failed run_id=%s error=%s",
                session.run_id,
                _rm_exc,
            )

        # 9. Restore _gate_pending state only if gate was not subsequently resolved.
        _last_gate_event: dict | None = None
        for ev in reversed(session.events):
            if isinstance(ev, dict) and ev.get("event") in ("gate_registered", "gate_decision"):
                _last_gate_event = ev
                break

        if _last_gate_event is not None and _last_gate_event.get("event") == "gate_registered":
            executor._gate_pending = _last_gate_event.get("gate_id")
            _logger.info(
                "runner.checkpoint_gate_restored run_id=%s gate_id=%s",
                executor.run_id,
                _last_gate_event.get("gate_id"),
            )
        # If last event was gate_decision: gate was resolved; _gate_pending stays None

        # 10. Execute remaining stages only
        return executor._execute_remaining()

    # -----------------------------------------------------------------------
    # Human Gate public API (Task 1 — P1-5)
    # -----------------------------------------------------------------------

    def register_gate(
        self,
        gate_id: str,
        gate_type: str = "final_approval",
        phase_name: str = "",
        recommendation: str = "",
        output_summary: str = "",
    ) -> None:
        """Register a named human gate point on this run."""
        return self.gate_coordinator.register_gate(
            gate_id=gate_id,
            gate_type=gate_type,
            phase_name=phase_name,
            recommendation=recommendation,
            output_summary=output_summary,
        )

    def resume(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
    ) -> None:
        """Resume execution after a human decision on a registered gate."""
        return self.gate_coordinator.resume(
            gate_id=gate_id,
            decision=decision,
            rationale=rationale,
        )

    def continue_from_gate(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
    ) -> RunResult:
        """Resume execution after a human gate decision."""
        return self.gate_coordinator.continue_from_gate(
            gate_id=gate_id,
            decision=decision,
            rationale=rationale,
        )

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
        return self.gate_coordinator.continue_from_gate_graph(
            gate_id=gate_id,
            decision=decision,
            rationale=rationale,
            last_stage=last_stage,
            completed_stages=completed_stages,
        )

    # -----------------------------------------------------------------------
    # Sub-run delegation public API
    # -----------------------------------------------------------------------

    def dispatch_subrun(
        self,
        agent: str,
        profile_id: str,
        strategy: str = "sequential",
        restart_policy: str = "reflect(2)",
        goal: str = "",
        agent_role: Any | None = None,
    ) -> SubRunHandle:
        """Dispatch a child run via DelegationManager.

        Builds a :class:`~hi_agent.task_mgmt.delegation.DelegationRequest`
        from the supplied parameters, submits it, and returns a
        :class:`SubRunHandle` that identifies the spawned sub-run.

        ``profile_id`` must equal the parent run's profile_id to maintain
        identity continuity.

        Args:
            agent: Agent role name for the child run.
            profile_id: Profile that governs the child run.
            strategy: Execution strategy hint (e.g. ``"sequential"``,
                ``"parallel"``).
            restart_policy: Restart policy expression (e.g.
                ``"reflect(2)"``).
            goal: Task instruction for the child run. When omitted the
                agent name is used as a fallback goal.
            agent_role: Optional :class:`~hi_agent.contracts.team_runtime.AgentRole`
                providing a typed role identity. When supplied, ``role_id`` is
                added to the delegation config so the child run can inherit it.
                When ``None``, existing behaviour is unchanged.

        Returns:
            A :class:`SubRunHandle` with the child run identifier.

        Raises:
            RuntimeError: If no DelegationManager is configured.
        """
        import uuid

        from hi_agent.task_mgmt.delegation import DelegationRequest

        if self._delegation_manager is None:
            raise RuntimeError(
                "dispatch_subrun requires a DelegationManager; "
                "inject one via RunExecutor(delegation_manager=...)"
            )

        task_id = f"{self.run_id}-sub-{uuid.uuid4().hex[:8]}"
        config: dict[str, Any] = {
            "agent": agent,
            "profile_id": profile_id,
            "strategy": strategy,
            "restart_policy": restart_policy,
        }
        if agent_role is not None:
            role_id = getattr(agent_role, "role_id", None)
            if role_id:
                config["role_id"] = role_id
        req = DelegationRequest(
            goal=goal or f"agent={agent}",
            task_id=task_id,
            config=config,
        )

        # delegate() is async; run it to completion in a new event loop if
        # we are not already inside one (synchronous call path).
        try:
            loop = asyncio.get_running_loop()
            # We ARE in an async context — create a task and return the handle.
            # The caller must await_subrun() to collect the result.
            future = loop.create_task(
                self._delegation_manager.delegate([req], parent_run_id=self.run_id)
            )
            future.add_done_callback(
                _make_subrun_done_callback(self._completed_subrun_results, task_id)
            )
            self._pending_subrun_futures[task_id] = future  # type: ignore[attr-defined]  expiry_wave: Wave 27
        except RuntimeError:
            # No running loop — synchronous call path.
            # DF-06: route through sync_bridge (Rule 12) to share a single
            # background loop across sync entry points.
            from hi_agent.runtime.sync_bridge import get_bridge

            results = get_bridge().call_sync(
                self._delegation_manager.delegate([req], parent_run_id=self.run_id)
            )
            self._completed_subrun_results[task_id] = results[0]  # type: ignore[attr-defined]  expiry_wave: Wave 27

        return SubRunHandle(subrun_id=task_id, agent=agent)

    def await_subrun(self, handle: SubRunHandle) -> SubRunResult:
        """Wait for a dispatched sub-run and return its result.

        Args:
            handle: Handle returned by :meth:`dispatch_subrun`.

        Returns:
            A :class:`SubRunResult` with completion status and output.
        """
        subrun_id = handle.subrun_id

        # Case 1: result already collected (synchronous dispatch path).
        completed = getattr(self, "_completed_subrun_results", {})
        if subrun_id in completed:
            dr = completed.pop(subrun_id)
            if dr.status == "gate_pending":
                return SubRunResult(
                    success=False,
                    output="",
                    error=None,
                    gate_id=getattr(dr, "gate_id", None),
                    status="gate_pending",
                )
            return SubRunResult(
                success=dr.status == "completed",
                output=dr.summary or dr.raw_output or "",
                error=dr.error,
            )

        # Case 2: future pending (async dispatch path).
        pending = getattr(self, "_pending_subrun_futures", {})
        if subrun_id in pending:
            future = pending[subrun_id]
            try:
                asyncio.get_running_loop()
                # A loop is running — this future belongs to it.
                if hasattr(future, "done") and future.done():
                    pending.pop(subrun_id)
                    results = future.result()
                else:
                    raise RuntimeError(
                        f"await_subrun() cannot block on sub-run {subrun_id!r} from "
                        "an async context while the task is still running. "
                        "Use `await executor.await_subrun_async(handle)` instead."
                    )
            except RuntimeError as _exc:
                if "await_subrun" in str(_exc):
                    raise
                # No running loop — synchronous path.
                pending.pop(subrun_id)

                async def _collect():
                    return await future

                # DF-06: route through sync_bridge (Rule 12) so the pending
                # future — created on the bridge loop — is awaited on that
                # same loop rather than a fresh asyncio.run loop.
                from hi_agent.runtime.sync_bridge import get_bridge

                results = get_bridge().call_sync(_collect())

            dr = results[0]
            if dr.status == "gate_pending":
                return SubRunResult(
                    success=False,
                    output="",
                    error=None,
                    gate_id=getattr(dr, "gate_id", None),
                    status="gate_pending",
                )
            return SubRunResult(
                success=dr.status == "completed",
                output=dr.summary or dr.raw_output or "",
                error=dr.error,
            )

        # Case 3: unknown handle — return a failure result rather than raising.
        _logger.warning(
            "runner.await_subrun_unknown_handle run_id=%s subrun_id=%s",
            self.run_id,
            subrun_id,
        )
        return SubRunResult(
            success=False,
            output="",
            error=f"No pending or completed result for subrun_id={subrun_id!r}",
        )

    async def await_subrun_async(self, handle: SubRunHandle) -> SubRunResult:
        """Async-safe variant of await_subrun() for use inside execute_async() stages.

        Must be used when dispatch_subrun() was called from within a running
        event loop. The sync await_subrun() raises RuntimeError in that context
        when the sub-run is still in progress.

        Args:
            handle: Handle returned by dispatch_subrun().

        Returns:
            SubRunResult with completion status and output.
        """
        subrun_id = handle.subrun_id

        completed = getattr(self, "_completed_subrun_results", {})
        if subrun_id in completed:
            dr = completed.pop(subrun_id)
            if dr.status == "gate_pending":
                return SubRunResult(
                    success=False,
                    output="",
                    error=None,
                    gate_id=getattr(dr, "gate_id", None),
                    status="gate_pending",
                )
            return SubRunResult(
                success=dr.status == "completed",
                output=dr.summary or dr.raw_output or "",
                error=dr.error,
            )

        pending = getattr(self, "_pending_subrun_futures", {})
        if subrun_id in pending:
            future = pending.pop(subrun_id)
            results = await future  # correct: same event loop
            dr = results[0]
            if dr.status == "gate_pending":
                return SubRunResult(
                    success=False,
                    output="",
                    error=None,
                    gate_id=getattr(dr, "gate_id", None),
                    status="gate_pending",
                )
            return SubRunResult(
                success=dr.status == "completed",
                output=dr.summary or dr.raw_output or "",
                error=dr.error,
            )

        _logger.warning(
            "runner.await_subrun_async_unknown_handle run_id=%s subrun_id=%s",
            self.run_id,
            subrun_id,
        )
        return SubRunResult(
            success=False,
            output="",
            error=f"No pending or completed result for subrun_id={subrun_id!r}",
        )


# ---------------------------------------------------------------------------
# Async execution support
# ---------------------------------------------------------------------------


@dataclass
class AsyncRunResult:
    """Async execution result from execute_async() (graph/scheduler path)."""

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

    Returns:
        A :class:`~hi_agent.contracts.requests.RunResult` identical in
        structure to the one returned by :meth:`RunExecutor.execute`.  This
        includes ``run_id``, ``status``, ``stages``, ``artifacts``,
        ``execution_provenance``, and failure attribution fields.

    .. note::
        **Not wired into the server RunManager.** ``POST /runs`` dispatches
        ``executor.execute()`` (synchronous, linear), not this function.
    """
    from hi_agent.task_mgmt.async_scheduler import AsyncTaskScheduler
    from hi_agent.task_mgmt.graph_factory import GraphFactory

    scheduler = AsyncTaskScheduler(kernel=executor.kernel, max_concurrency=max_concurrency)

    factory = GraphFactory()
    # S2 fix (SA-A7-async-graph): when the executor owns a concrete
    # stage_graph (set by SystemBuilder / test harness / resumed run) we
    # mirror its stage identities into the async TrajectoryGraph so gates
    # registered on those stages actually fire under execute_async().
    # auto_select() is retained as a fallback for callers that supply an
    # executor without a stage_graph (e.g. pure goal-driven entry points).
    _existing_stage_graph = getattr(executor, "stage_graph", None)
    if _existing_stage_graph is not None and getattr(_existing_stage_graph, "transitions", None):
        _template_name = "from_stage_graph"
        graph = factory.from_stage_graph(_existing_stage_graph)
    else:
        _template_name, graph = factory.auto_select(
            goal=executor.contract.goal,
            task_family=getattr(executor.contract, "task_family", ""),
        )

    # DF-16 / K-2 / K-3 / K-15: async path must mirror sync path invariants (Rule 5 branch parity).
    # Sync execute() calls `self.kernel.start_run(self.contract.task_id)` and assigns the
    # returned run_id to `self._run_id`. The async path must use the IDENTICAL signature —
    # the RuntimeAdapter protocol defines `start_run(task_id: str) -> str`, and the previous
    # kwarg form (`run_id=, session_id=, metadata=`) did not match any concrete adapter.
    _start_result = executor.kernel.start_run(executor.contract.task_id)
    if inspect.isawaitable(_start_result):
        run_id = await _start_result
    else:
        run_id = _start_result
    executor._run_id = run_id  # K-2: sync executor's run_id to match kernel registration
    executor._run_start_monotonic = time.monotonic()  # K-15: enable duration measurement

    # When the stage kernel (sync) differs from executor.kernel (async facade),
    # pre-register the run_id so open_branch / mark_branch_state can locate it.
    _sk = getattr(executor._stage_executor, "kernel", None)
    if (
        _sk is not None
        and _sk is not executor.kernel
        and hasattr(_sk, "runs")
        and run_id not in _sk.runs
    ):
        _sk.runs[run_id] = {
            "run_id": run_id,
            "task_id": executor.contract.task_id,
            "status": "running",
            "cancel_reason": None,
            "signals": [],
            "plan": None,
        }

    async def make_handler(node_id: str):
        async def handler(action, grant):
            from hi_agent.gate_protocol import GatePendingError as _GatePE

            # S2 fix: when the async node graph was mirrored from the
            # executor's stage_graph (via factory.from_stage_graph), the
            # node_id IS a real stage_id in the gate_coordinator namespace.
            # We must drive ``executor._execute_stage(node_id)`` so gates
            # registered on those stages can fire — even when the async
            # kernel's open_stage isn't directly sync-callable. The stage
            # executor internally handles sync-vs-async kernel dispatch.
            _stage_kernel = getattr(executor._stage_executor, "kernel", None)
            _sync_capable = (
                _stage_kernel is not None
                and callable(getattr(_stage_kernel, "open_stage", None))
                and not inspect.iscoroutinefunction(getattr(_stage_kernel, "open_stage", None))
            )
            _use_stage_executor = _sync_capable or _template_name == "from_stage_graph"
            if _use_stage_executor:
                # Rule 5 — `handler` is an async function, so the
                # caller's loop is already running. ``get_running_loop()``
                # returns it without creating a new one (and raises if
                # somehow invoked outside an async context, which would be
                # a bug to surface, not paper over).
                loop = asyncio.get_running_loop()
                try:
                    result = await loop.run_in_executor(None, executor._execute_stage, node_id)
                except Exception as _stage_exc:
                    if isinstance(_stage_exc, _GatePE):
                        raise
                    result = "failed"
                status = "failed" if result == "failed" else "completed"
            else:
                # Async-only kernel with no stage_graph mirroring — state is
                # managed by execute_turn; no sync stage methods available.
                # Still honour any gate that was raised before this node ran.
                if executor._gate_pending is not None:
                    raise _GatePE(gate_id=executor._gate_pending)
                status = "completed"
            return {"node_id": node_id, "status": status}

        return handler

    # --- Sub-goal delegation: dispatch child runs when contract exposes sub_goals ---
    # The contract schema does not require sub_goals; check defensively so that
    # this path is safely skipped when the field is absent or empty.
    _sub_goals: list[Any] = getattr(executor.contract, "sub_goals", None) or []
    if _sub_goals and executor._delegation_manager is not None:
        from hi_agent.task_mgmt.delegation import DelegationRequest

        delegation_requests = [
            DelegationRequest(
                goal=str(sg),
                task_id=f"{run_id}-sub-{idx}",
            )
            for idx, sg in enumerate(_sub_goals)
        ]
        try:
            delegation_results = await executor._delegation_manager.delegate(
                delegation_requests, parent_run_id=run_id
            )
            _logger.info(
                "execute_async: delegated %d sub-goals for run_id=%s; results=%s",
                len(delegation_results),
                run_id,
                [(r.status, r.request.goal[:40]) for r in delegation_results],
            )
        except Exception as _exc:
            _logger.warning("execute_async: delegation failed for run_id=%s: %s", run_id, _exc)

    schedule_result = await scheduler.run(
        graph=graph,
        run_id=run_id,
        make_handler=make_handler,
    )

    # J3-3: Populate session.stage_states so a resumed run does not re-execute.
    if executor.session is not None:
        for node_id in schedule_result.completed_nodes:
            executor.session.stage_states[node_id] = "completed"

    # J3-2: _finalize_run handles resource cleanup and provenance for RunResult.
    outcome = "completed" if schedule_result.success else "failed"
    _run_result: RunResult | None = None
    try:
        _run_result = executor._finalize_run(outcome)
    except Exception as _fin_exc:
        try:
            from hi_agent.observability.fallback import record_fallback

            record_fallback(
                "llm",
                reason="finalize_failed",
                run_id=run_id,
                extra={"exc": str(_fin_exc)},
            )
        except Exception as _rec_exc:
            from hi_agent.observability.silent_degradation import (
                record_silent_degradation,
            )

            record_silent_degradation(
                component="runner._record_fallback_self_failure",
                reason="fallback_record_failed",
                run_id=run_id,
                exc=_rec_exc,
            )
        _logger.warning("execute_async: _finalize_run failed: %s", _fin_exc)

    if _run_result is not None:
        return _run_result

    # Fallback: _finalize_run failed or returned None — construct minimal RunResult.
    try:
        from hi_agent.observability.fallback import get_fallback_events, record_fallback

        _fb_events = get_fallback_events(run_id)
    except Exception as _fe_exc:
        import contextlib

        with contextlib.suppress(Exception):  # rule7-exempt:  expiry_wave: Wave 27
            record_fallback(
                "llm",
                reason="fallback_events_lookup_failed",
                run_id=run_id,
                extra={"exc": str(_fe_exc)},
            )
        _fb_events = []  # still fall back to empty after recording the alarm
    return RunResult(
        run_id=run_id,
        status=outcome,
        stages=[],
        artifacts=[],
        fallback_events=_fb_events,
    )
