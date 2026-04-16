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
    NodeState,
    StageState,
    StageSummary,
    TaskContract,
    TrajectoryNode,
    deterministic_id,
)
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.contracts.requests import RunResult
from hi_agent.events import EventEmitter, EventEnvelope
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


def _reflect_task_done_callback(task: asyncio.Task[object]) -> None:
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


def _subrun_task_done_callback(task: asyncio.Task[object]) -> None:
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


def _make_subrun_done_callback(
    results_dict: "dict[str, object]", task_id: str
) -> "Callable[[asyncio.Task[object]], None]":
    """Create a done-callback that stores task-level failures into results_dict."""

    def _cb(task: asyncio.Task[object]) -> None:
        if task.cancelled():
            _logger.warning(
                "runner.subrun_async_task_cancelled task_id=%s", task_id
            )
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
        mid_term_store: MidTermMemoryStore | None = None,
        long_term_consolidator: LongTermConsolidator | None = None,
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
        self.invoker = invoker or self._build_default_invoker(llm_gateway)
        self._invoker_accepts_role, self._invoker_accepts_metadata = (
            self._supports_optional_invoke_arguments(self.invoker.invoke)
        )
        self.current_stage = ""
        self.cts_budget = cts_budget or CTSExplorationBudget()
        self._total_branches_opened = 0
        self._stage_active_branches: dict[str, int] = {}
        self._compress_snip_threshold = compress_snip_threshold
        self._compress_window_threshold = compress_window_threshold
        self._compress_compress_threshold = compress_compress_threshold
        self.evolve_engine = evolve_engine
        self.harness_executor = harness_executor
        self.human_gate_quality_threshold = human_gate_quality_threshold
        self._gate_seq = 0
        # Registered human gate events, keyed by gate_id.
        self._registered_gates: dict[str, object] = {}
        # gate_id of the currently blocking human gate, or None if no gate is pending.
        self._gate_pending: str | None = None
        # Pending async delegation futures, keyed by task_id.
        self._pending_subrun_futures: dict[str, object] = {}
        # Completed synchronous delegation results, keyed by task_id.
        self._completed_subrun_results: dict[str, object] = {}
        # Pending async reflection background tasks, tracked for cancellation on finalize.
        self._pending_reflection_tasks: list[object] = []
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
                if hasattr(self.route_engine, '_context_provider'):
                    self.route_engine._context_provider = (
                        lambda: self.session.build_context_for_llm("routing")
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
            route_engine=self.route_engine,
            tier_router=self.tier_router,
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

        # --- Fix-4: ExecutionHookManager — wraps capability invocations so all
        #     registered pre/post hooks fire around every action execution. ---
        try:
            from hi_agent.middleware.hooks import ExecutionHookManager, HookRegistry
            self._hook_registry = HookRegistry()
            self._hook_manager = ExecutionHookManager(self._hook_registry)
        except Exception as _exc:
            _logger.debug(
                "runner.hook_manager_init_failed run_id=%s error=%s",
                self.run_id, _exc,
            )
            self._hook_registry = None
            self._hook_manager = None

        # --- Fix-5: NudgeInjector — periodically injects memory/skill nudges
        #     into the agent's context to drive continuous evolution (P1). ---
        try:
            from hi_agent.context.nudge import NudgeConfig, NudgeInjector, NudgeState
            self._nudge_config = NudgeConfig(
                memory_nudge_interval=getattr(
                    getattr(self, 'config', None), 'memory_nudge_interval', 10
                ),
                skill_nudge_interval=getattr(
                    getattr(self, 'config', None), 'skill_nudge_interval', 15
                ),
                enabled=getattr(
                    getattr(self, 'config', None), 'nudge_enabled', True
                ),
            )
            self._nudge_injector = NudgeInjector(self._nudge_config)
            self._nudge_state = NudgeState()
        except Exception as _exc:
            _logger.debug(
                "runner.nudge_injector_init_failed run_id=%s error=%s",
                self.run_id, _exc,
            )
            self._nudge_injector = None
            self._nudge_state = None
        # Pending nudge blocks to be prepended to the next task-view payload.
        self._pending_nudge_blocks: list[dict] = []

        # --- RestartPolicyEngine + ReflectionOrchestrator (optional, injected) ---
        self._restart_policy: RestartPolicyEngine | None = restart_policy_engine
        self._reflection_orchestrator: ReflectionOrchestrator | None = (
            reflection_orchestrator
        )
        # Per-stage retry attempt counters used by _handle_stage_failure
        self._stage_attempt: dict[str, int] = {}

        # --- DelegationManager: parallel child-run delegation (optional) ---
        self._delegation_manager: DelegationManager | None = delegation_manager

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

    # ------------------------------------------------------------------
    # Fix-4: ExecutionHookManager helpers
    # ------------------------------------------------------------------

    def _invoke_capability_via_hooks(
        self, proposal: object, payload: dict
    ) -> dict:
        """Invoke capability through ExecutionHookManager pre/post tool hooks.

        When _hook_manager is available, wraps the raw capability invocation
        so that all registered pre_tool and post_tool hooks fire around it.
        Falls back to direct invocation if hooks are unavailable.
        """
        if self._hook_manager is None:
            return self._invoke_capability(proposal, payload)

        try:
            import asyncio
            import concurrent.futures as _cf

            from hi_agent.middleware.hooks import ToolCallContext

            tool_ctx = ToolCallContext(
                run_id=self.run_id,
                stage_id=payload.get("stage_id", self.current_stage or ""),
                tool_name=str(getattr(proposal, "action_kind", "unknown")),
                tool_input=payload,
                turn_number=self.action_seq,
            )

            def _call_fn(_ctx: ToolCallContext) -> str:
                result = self._invoke_capability(proposal, payload)
                # Store result so we can return it after hook chain completes
                _call_fn._last_result = result  # type: ignore[attr-defined]
                return str(result.get("success", False))

            _call_fn._last_result = {}  # type: ignore[attr-defined]

            # Run async hook chain synchronously
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're inside execute_async() — run hook chain in a fresh
                    # thread to avoid nested event loop.  concurrent.futures +
                    # asyncio.run() creates an isolated loop in the worker thread.
                    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                        _pool.submit(
                            asyncio.run,
                            self._hook_manager.wrap_tool_call(tool_ctx, _call_fn),
                        ).result()
                else:
                    loop.run_until_complete(
                        self._hook_manager.wrap_tool_call(tool_ctx, _call_fn)
                    )
            except RuntimeError:
                asyncio.run(
                    self._hook_manager.wrap_tool_call(tool_ctx, _call_fn)
                )

            return _call_fn._last_result  # type: ignore[attr-defined]
        except Exception as exc:
            _logger.debug(
                "runner.hook_wrap_failed run_id=%s stage_id=%s error=%s",
                self.run_id, payload.get("stage_id", ""), exc,
            )
            return self._invoke_capability(proposal, payload)

    # ------------------------------------------------------------------
    # Fix-5: NudgeInjector helpers
    # ------------------------------------------------------------------

    def _nudge_check_after_action(
        self, stage_id: str, action_text: str = ""
    ) -> None:
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
                memory_saved, skill_created = ActionDetector.detect_from_text(
                    action_text
                )
                if memory_saved:
                    self._nudge_state.reset_memory()
                if skill_created:
                    self._nudge_state.reset_skill()

            self._nudge_state.increment_turn()
            self._nudge_state.increment_iter()

            triggers = self._nudge_injector.check(self._nudge_state)
            if triggers:
                blocks = [
                    self._nudge_injector.to_system_block(t) for t in triggers
                ]
                self._pending_nudge_blocks.extend(blocks)
                _logger.debug(
                    "runner.nudge_triggered run_id=%s stage_id=%s nudges=%d",
                    self.run_id, stage_id, len(triggers),
                )
        except Exception as exc:
            _logger.debug(
                "runner.nudge_check_failed run_id=%s stage_id=%s error=%s",
                self.run_id, stage_id, exc,
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

    def _build_default_invoker(
        self, llm_gateway: Any | None = None
    ) -> CapabilityInvoker:
        """Build a default capability invoker with built-in action handlers.

        Args:
            llm_gateway: Optional LLM gateway for model-backed capability
                execution.  When provided, each default handler calls the LLM
                and falls back to a heuristic on failure.
        """
        registry = CapabilityRegistry()
        register_default_capabilities(registry, llm_gateway=llm_gateway)
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
        written to the replay JSONL log.  Each event is also published to
        the process-local EventBus so that SSE subscribers receive live
        updates.
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
        # Publish to SSE EventBus so /events subscribers receive live updates.
        try:
            import datetime as _dt
            import uuid as _uuid

            from agent_kernel.kernel.contracts import RuntimeEvent as _RuntimeEvent

            from hi_agent.server.event_bus import event_bus as _event_bus
            _event_bus.publish(_RuntimeEvent(
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
            ))
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
        self,
        stage_id: str,
        proposal: object,
        *,
        upstream_artifact_ids: list[str] | None = None,
    ) -> tuple[bool, dict | None, int]:
        """Execute one action with retry semantics.

        Args:
            stage_id: Current stage identifier.
            proposal: Route proposal for the action.
            upstream_artifact_ids: Artifact IDs produced by prior actions in
                this stage.  Threaded through to the harness so artifact
                lineage is recorded on outputs.

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
                "upstream_artifact_ids": upstream_artifact_ids or [],
            }
            self._record_event("ActionPlanned", payload)

            try:
                # Fix-4: route through ExecutionHookManager (pre/post tool hooks)
                result = self._invoke_capability_via_hooks(proposal, payload)
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
                # Fix-5: nudge check after each completed action attempt
                action_text = str(result) if result else ""
                self._nudge_check_after_action(stage_id, action_text)
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
            upstream_artifact_ids=list(
                payload.get("upstream_artifact_ids") or []
            ),
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
            "artifact_ids": result.artifact_ids,
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
                dl = datetime.fromisoformat(
                    self.contract.deadline.replace("Z", "+00:00")
                )
                if datetime.now(UTC) >= dl:
                    self._record_failure(
                        "execution_budget_exhausted",
                        f"Task deadline exceeded: {self.contract.deadline}",
                        stage_id=stage_id,
                    )
                    _logger.warning(
                        "runner.deadline_exceeded run_id=%s stage_id=%s deadline=%s",
                        self.run_id, stage_id, self.contract.deadline,
                    )
                    return "failed"
            except (ValueError, TypeError):
                pass  # malformed deadline string — ignore rather than crash
        return self._stage_executor.execute_stage(stage_id, executor=self)

    def _cancel_pending_subruns(self, status: str) -> None:
        """Cancel any sub-run futures and reflection tasks not collected before finalization."""
        # J8-1: Cancel orphaned reflection background tasks.
        for task in list(getattr(self, "_pending_reflection_tasks", [])):
            try:
                if callable(getattr(task, "done", None)) and not task.done():
                    task.cancel()
                    _logger.warning(
                        "runner.reflect_task_cancelled_at_finalization run_id=%s",
                        self.run_id,
                    )
            except Exception as _exc:
                _logger.debug("runner.reflect_task_cancel_failed error=%s", _exc)
        _pending_reflect = getattr(self, "_pending_reflection_tasks", [])
        _pending_reflect.clear()

        pending = getattr(self, "_pending_subrun_futures", {})
        for task_id, future in list(pending.items()):
            try:
                if callable(getattr(future, "done", None)) and not future.done():
                    future.cancel()
                    _logger.warning(
                        "runner.subrun_cancelled_at_finalization "
                        "task_id=%s run_status=%s run_id=%s",
                        task_id, status, self.run_id,
                    )
            except Exception as _exc:
                _logger.warning(
                    "runner.subrun_cancel_failed task_id=%s error=%s", task_id, _exc
                )
        pending.clear()
        completed = getattr(self, "_completed_subrun_results", {})
        if completed:
            _logger.debug(
                "runner.subrun_uncollected_results_cleared count=%d run_id=%s",
                len(completed), self.run_id,
            )
            completed.clear()

    def _finalize_run(self, outcome: str) -> RunResult:
        """Run post-execution finalization for a given outcome.

        Handles observability, evolve engine, skill outcomes, episode
        building, cost summary, short-term memory, and knowledge ingestion.

        Returns:
            A structured :class:`~hi_agent.contracts.requests.RunResult`
            containing run_id, status, per-stage summaries, and artifact IDs.
            ``str(result)`` returns the status string for backward compatibility.
        """
        self._cancel_pending_subruns(outcome)

        # Flush and close L0 JSONL before L0Summarizer reads it.
        if getattr(self, "raw_memory", None) is not None:
            try:
                self.raw_memory.close()
            except Exception as _exc:
                _logger.warning("runner.raw_memory_close_failed error=%s", _exc)

        self._lifecycle.finalize_run(
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
        # Build structured result from accumulated stage summaries.
        stage_dicts: list[dict] = []
        all_artifact_ids: list[str] = []
        for stage_id, summary in self.stage_summaries.items():
            stage_dicts.append({
                "stage_id": stage_id,
                "stage_name": getattr(summary, "stage_name", stage_id),
                "outcome": getattr(summary, "outcome", "unknown"),
                "findings": list(getattr(summary, "findings", [])),
                "decisions": list(getattr(summary, "decisions", [])),
                "artifact_ids": list(getattr(summary, "artifact_ids", [])),
            })
            all_artifact_ids.extend(getattr(summary, "artifact_ids", []))

        # --- Failure attribution ---
        failed_stage_id: str | None = None
        error_detail: str | None = None
        failure_code: str | None = None
        is_retryable: bool = False

        if outcome != "completed":
            failed_stage_id = self.current_stage
            # Prefer exception message captured during execute()
            exc_msg = getattr(self, "_last_exception_msg", None)
            if exc_msg:
                error_detail = exc_msg
            else:
                # Fall back to the failed stage's outcome info
                summary = self.stage_summaries.get(failed_stage_id or "")
                if summary is not None:
                    stage_outcome = getattr(summary, "outcome", "")
                    if stage_outcome and stage_outcome != "succeeded":
                        error_detail = f"Stage {failed_stage_id!r} outcome: {stage_outcome}"
            if not error_detail:
                error_detail = f"Run failed at stage {failed_stage_id!r}"
            # Precise failure attribution: query FailureCollector for structured record.
            # Map raw outcome strings to proper FailureCode enum values.
            _OUTCOME_TO_FAILURE_CODE = {
                "failed": "no_progress",
                "aborted": "exploration_budget_exhausted",
                "timeout": "callback_timeout",
                "unsafe": "unsafe_action_blocked",
            }
            failure_code = _OUTCOME_TO_FAILURE_CODE.get(outcome, outcome)
            is_retryable = False
            collector = getattr(self, "failure_collector", None)
            if collector is not None:
                try:
                    from hi_agent.failures.taxonomy import FAILURE_RECOVERY_MAP
                    unresolved = collector.get_unresolved()
                    last_failure = unresolved[-1] if unresolved else None
                    if last_failure is None:
                        all_records = collector.get_all()
                        last_failure = all_records[-1] if all_records else None
                    if last_failure is not None:
                        # Use real FailureCode instead of bare outcome string
                        fc = last_failure.failure_code
                        failure_code = fc.value if hasattr(fc, "value") else str(fc)
                        # Enrich error_detail with FailureRecord message
                        if last_failure.message:
                            error_detail = last_failure.message
                        # Enrich failed_stage_id from FailureRecord
                        if last_failure.stage_id:
                            failed_stage_id = last_failure.stage_id
                        # Determine retryability from FAILURE_RECOVERY_MAP
                        recovery = FAILURE_RECOVERY_MAP.get(fc, "")
                        is_retryable = recovery in (
                            "retry_or_downgrade_model",
                            "recovery_path",
                            "task_view_degradation",
                            "watchdog_handling",
                        )
                except Exception as _attr_exc:
                    _logger.debug("Failure attribution enrichment failed: %s", _attr_exc)
            # Final fallback: retryable if a restart policy engine is wired
            if not is_retryable:
                is_retryable = getattr(self, "_restart_policy", None) is not None

        # Cross-validate stage summaries against final outcome.
        # The failed stage cannot show "succeeded" or "active" — the compressor
        # may mark it "succeeded" if any branch completed, or "active" if the
        # stage was interrupted before an explicit completion event was recorded.
        if outcome != "completed" and failed_stage_id is not None:
            for sd in stage_dicts:
                if sd["stage_id"] == failed_stage_id and sd.get("outcome") in ("succeeded", "active", "unknown"):
                    sd["outcome"] = "failed"

        # --- Acceptance criteria evaluation ---
        # If outcome is "completed", verify declared acceptance_criteria.
        # Supported formats:
        #   "required_stage:<stage_id>"  — stage must have outcome "succeeded"
        #   "required_artifact:<artifact_id>" — artifact_id must be present
        # Any failing criterion downgrades outcome to "failed".
        if outcome == "completed":
            criteria = getattr(self.contract, "acceptance_criteria", None) or []
            criteria_failures: list[str] = []
            completed_stage_ids = {sd["stage_id"] for sd in stage_dicts if sd.get("outcome") == "succeeded"}
            for criterion in criteria:
                if not isinstance(criterion, str):
                    continue
                if criterion.startswith("required_stage:"):
                    required_sid = criterion[len("required_stage:"):]
                    if required_sid not in completed_stage_ids:
                        criteria_failures.append(criterion)
                elif criterion.startswith("required_artifact:"):
                    required_aid = criterion[len("required_artifact:"):]
                    if required_aid not in all_artifact_ids:
                        criteria_failures.append(criterion)
            if criteria_failures:
                outcome = "failed"
                failure_code = "invalid_context"
                error_detail = f"Acceptance criteria not met: {criteria_failures}"
                _logger.warning(
                    "runner.acceptance_criteria_failed run_id=%s criteria=%s",
                    self.run_id, criteria_failures,
                )

        # --- Exception-type → failure_code improvement (P2-NEW-03) ---
        # When outcome is failed and failure_code is still the naive default,
        # use the captured exception type for more precise attribution.
        if outcome != "completed" and failure_code == "no_progress":
            exc_type = getattr(self, "_last_exception_type", None)
            if exc_type:
                _EXC_TYPE_TO_FAILURE_CODE: dict[str, str] = {
                    "TimeoutError": "callback_timeout",
                    "asyncio.TimeoutError": "callback_timeout",
                    "concurrent.futures.TimeoutError": "callback_timeout",
                    "MemoryError": "execution_budget_exhausted",
                    "RecursionError": "execution_budget_exhausted",
                    "PermissionError": "harness_denied",
                    "KeyError": "invalid_context",
                    "ValueError": "invalid_context",
                    "TypeError": "invalid_context",
                }
                mapped = _EXC_TYPE_TO_FAILURE_CODE.get(exc_type)
                if mapped:
                    failure_code = mapped

        # --- L0 -> L2 consolidation ---
        try:
            from pathlib import Path as _Path
            _raw_run_id = getattr(self.raw_memory, "_run_id", "")
            _raw_file = getattr(self.raw_memory, "_file", None)
            # Attempt to derive base_dir from the log path stored on the store
            _raw_base = getattr(self.raw_memory, "_base_dir", None)
            if _raw_base is None and _raw_run_id:
                # Fallback: check if RawMemoryStore exposed _base_dir_path
                _raw_base = getattr(self.raw_memory, "_base_dir_path", None)
            if _raw_base is not None:
                from hi_agent.memory.l0_summarizer import L0Summarizer
                _summary = L0Summarizer().summarize_run(self.run_id, _Path(_raw_base))
                if _summary is not None and self.mid_term_store is not None:
                    self.mid_term_store.save(_summary)
        except Exception as _cons_exc:  # consolidation must never crash the run
            _logger.debug("L0->L2 consolidation failed: %s", _cons_exc)

        # --- L2 -> L3 consolidation ---
        _consolidator = self.long_term_consolidator
        if _consolidator is not None:
            try:
                _consolidator.consolidate(days=1)
            except Exception as _exc:
                _logger.debug("L2->L3 consolidation failed: %s", _exc)

        # --- Wall-clock duration ---
        _start = getattr(self, "_run_start_monotonic", None)
        duration_ms = int((time.monotonic() - _start) * 1000) if _start is not None else 0

        return RunResult(
            run_id=self.run_id,
            status=outcome,
            stages=stage_dicts,
            artifacts=all_artifact_ids,
            error=error_detail,
            failure_code=failure_code,
            failed_stage_id=failed_stage_id,
            is_retryable=is_retryable,
            duration_ms=duration_ms,
        )

    def execute(self) -> RunResult:
        """Execute all stages with deterministic routing and capability dispatch.

        Returns:
          A structured :class:`~hi_agent.contracts.requests.RunResult`.
          For backward compatibility, ``str(result)`` returns the status string
          (``"completed"`` or ``"failed"``).
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

        self._run_start_monotonic: float = time.monotonic()
        try:
            for stage_id in self.stage_graph.trace_order():
                stage_result = self._execute_stage(stage_id)
                if stage_result == "failed":
                    handled = self._handle_stage_failure(stage_id, stage_result)
                    if handled == "failed":
                        return self._finalize_run("failed")
                    # "reflected" or any non-failed result: continue to next stage
        except GatePendingError:
            raise  # propagate — gate awaits human input, not a run failure
        except Exception as exc:
            # Capture exception type and message for failure attribution in RunResult.
            self._last_exception_msg: str | None = str(exc)
            self._last_exception_type: str | None = type(exc).__name__
            self._log_best_effort_exception(
                logging.WARNING,
                "runner.execute_failed",
                exc,
                run_id=self.run_id,
                stage_id=self.current_stage,
            )
            self._record_event("RunError", {"error": str(exc), "run_id": self.run_id})
            handled = self._handle_stage_failure(self.current_stage, "failed")
            if handled == "failed":
                return self._finalize_run("failed")
            # "reflected" or non-failed: continue to finalize as completed

        return self._finalize_run("completed")

    def execute_graph(self) -> RunResult:
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

        self._run_start_monotonic = time.monotonic()
        # Find start stage (zero indegree)
        current_stage = self._find_start_stage()
        completed_stages: set[str] = set()
        max_steps = len(self.stage_graph.transitions) * 2  # safety limit
        steps = 0

        try:
            while current_stage is not None and steps < max_steps:
                steps += 1
                result = self._execute_stage(current_stage)
                if result == "failed":
                    backtrack = self.stage_graph.get_backtrack(current_stage)
                    if backtrack and backtrack not in completed_stages:
                        # Backtrack: re-execute a previous stage
                        current_stage = backtrack
                        continue
                    handled = self._handle_stage_failure(current_stage, result)
                    if handled == "failed":
                        return self._finalize_run("failed")
                    # "reflected" or non-failed: treat as completed and continue
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
        except GatePendingError:
            raise  # propagate — gate awaits human input, not a run failure
        except Exception as exc:
            self._last_exception_msg = str(exc)
            self._last_exception_type = type(exc).__name__
            self._log_best_effort_exception(
                logging.WARNING, "runner.execute_graph_failed", exc,
                run_id=self.run_id, stage_id=self.current_stage,
            )
            return self._finalize_run("failed")

        return self._finalize_run("completed")

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
        # Honour a backtrack gate decision: run is terminated, no retry or reflect.
        if getattr(self, "_run_terminated", False):
            _logger.info(
                "runner.stage_failure_skipped_terminated stage_id=%s run_id=%s",
                stage_id, self.run_id,
            )
            return "failed"

        if self._restart_policy is None:
            return "failed"

        # K-7: hard safety ceiling against unbounded recursion
        _max_total_attempts = max_retries * 2 + 1
        try:
            for _loop_guard in range(_max_total_attempts):
                attempt = self._stage_attempt.get(stage_id, 0) + 1
                self._stage_attempt[stage_id] = attempt

                # Build a lightweight failure object the engine can inspect.
                class _StageFail:
                    retryability = "unknown"
                    failure_code = stage_result

                policy_task_id = self.contract.task_id

                # Record this attempt so reflect_and_infer() receives real history.
                try:
                    from datetime import UTC, datetime

                    from hi_agent.task_mgmt.restart_policy import TaskAttempt as _TA
                    _ta_kwargs: dict = dict(
                        attempt_id=f"{self.run_id}/{stage_id}/{attempt}",
                        task_id=policy_task_id,
                        run_id=self.run_id,
                        attempt_seq=attempt,
                        started_at=datetime.now(UTC).isoformat(),
                        outcome="failed",
                        failure=_StageFail(),
                    )
                    # stage_id was added in H-1; fall back gracefully if absent.
                    try:
                        ta_obj = _TA(**_ta_kwargs, stage_id=stage_id)
                    except TypeError:
                        ta_obj = _TA(**_ta_kwargs)
                        try:
                            object.__setattr__(ta_obj, "stage_id", stage_id)
                        except (AttributeError, TypeError):
                            pass
                    self._restart_policy._record_attempt(ta_obj)
                except Exception as _rec_exc:
                    _logger.debug(
                        "runner.record_attempt_failed stage_id=%s attempt=%d error=%s",
                        stage_id, attempt, _rec_exc,
                    )

                _policy = self._restart_policy._get_policy(policy_task_id)
                if _policy is None:
                    _logger.warning(
                        "runner: no restart policy for task_id=%s, defaulting to abort",
                        policy_task_id,
                    )
                    from hi_agent.task_mgmt.restart_policy import RestartDecision
                    decision = RestartDecision(
                        task_id=policy_task_id,
                        action="abort",
                        next_attempt_seq=None,
                        reason="no restart policy configured",
                    )
                else:
                    decision = self._restart_policy._decide(
                        _policy,
                        policy_task_id,
                        attempt,
                        _StageFail(),
                        stage_id=stage_id,
                    )

                _logger.info(
                    "runner.restart_decision stage_id=%s attempt=%d action=%s reason=%s",
                    stage_id,
                    attempt,
                    decision.action,
                    decision.reason,
                )

                if decision.action == "retry":
                    if attempt <= max_retries:
                        _logger.info(
                            "runner.stage_retry stage_id=%s attempt=%d/%d",
                            stage_id,
                            attempt,
                            max_retries,
                        )
                        retry_result = self._execute_stage(stage_id)
                        if retry_result != "failed":
                            return retry_result
                        stage_result = retry_result
                        continue  # K-7: loop back instead of recursing
                    _logger.warning(
                        "runner.stage_retry_exhausted stage_id=%s max_retries=%d",
                        stage_id,
                        max_retries,
                    )
                    return "failed"

                if decision.action == "reflect":
                    # Pinned retrieval: load prior reflection prompt by exact session_id to
                    # bypass list_recent() window limits. Best-effort — retry proceeds if unavailable.
                    if self.short_term_store is not None and attempt > 1:
                        try:
                            prior_session = f"{self.run_id}/reflect/{stage_id}/{attempt - 1}"
                            prior_mem = self.short_term_store.load(prior_session)
                            if prior_mem is not None and self.context_manager is not None:
                                self.context_manager.set_reflection_context(
                                    prior_mem.task_goal or ""
                                )
                        except Exception:
                            pass  # best-effort

                    # Inject reflection prompt into the run context so the next
                    # stage attempt has actionable guidance from the failure.
                    if decision.reflection_prompt is not None:
                        try:
                            self._record_event(
                                "ReflectionPrompt",
                                {
                                    "stage_id": stage_id,
                                    "run_id": self.run_id,
                                    "reflection_prompt": decision.reflection_prompt,
                                },
                            )
                        except Exception as exc:
                            _logger.warning(
                                "runner.reflect_prompt_record_failed stage_id=%s error=%s",
                                stage_id,
                                exc,
                            )
                    if self._reflection_orchestrator is not None:
                        try:
                            import asyncio

                            descriptor_cls = None
                            try:
                                from hi_agent.task_mgmt.reflection_bridge import (
                                    TaskDescriptor,
                                )
                                descriptor_cls = TaskDescriptor
                            except Exception as exc:
                                _logger.warning(
                                    "runner: task_descriptor import failed, reflection skipped: %s",
                                    exc,
                                )

                            if descriptor_cls is not None:
                                descriptor = descriptor_cls(
                                    task_id=policy_task_id,
                                    goal=getattr(self.contract, "goal", ""),
                                    context={},
                                )
                                loop = None
                                try:
                                    loop = asyncio.get_event_loop()
                                except RuntimeError as exc:
                                    _logger.warning(
                                        "runner: no event loop available, sync reflection only: %s",
                                        exc,
                                    )

                                if loop is not None and loop.is_running():
                                    # Save reflection prompt synchronously — must precede the retry LLM call.
                                    if decision.reflection_prompt and self.short_term_store is not None:
                                        try:
                                            from hi_agent.memory.short_term import (
                                                ShortTermMemory,
                                            )
                                            self.short_term_store.save(
                                                ShortTermMemory(
                                                    session_id=f"{self.run_id}/reflect/{stage_id}/{attempt}",
                                                    run_id=self.run_id,
                                                    task_goal=decision.reflection_prompt,
                                                    outcome="reflecting",
                                                )
                                            )
                                        except Exception as _exc:
                                            _logger.warning(
                                                "runner.reflect_context_inject_failed "
                                                "stage_id=%s error=%s",
                                                stage_id,
                                                _exc,
                                            )
                                    # Fire extended LLM reflection as a background task.
                                    task = loop.create_task(
                                        self._reflection_orchestrator.reflect_and_infer(
                                            descriptor=descriptor,
                                            attempts=self._get_attempt_history(stage_id),
                                            run_id=self.run_id,
                                        )
                                    )
                                    task.add_done_callback(_reflect_task_done_callback)
                                    self._pending_reflection_tasks.append(task)  # J8-1: track for finalization
                                    _logger.info(
                                        "runner.reflect_scheduled_async stage_id=%s",
                                        stage_id,
                                    )
                                else:
                                    asyncio.run(
                                        self._reflection_orchestrator.reflect_and_infer(
                                            descriptor=descriptor,
                                            attempts=self._get_attempt_history(stage_id),
                                            run_id=self.run_id,
                                        )
                                    )
                                    # Inject reflection prompt into short-term memory so retry LLM sees it.
                                    if decision.reflection_prompt and self.short_term_store is not None:
                                        try:
                                            from hi_agent.memory.short_term import (
                                                ShortTermMemory,
                                            )
                                            self.short_term_store.save(
                                                ShortTermMemory(
                                                    session_id=f"{self.run_id}/reflect/{stage_id}/{attempt}",
                                                    run_id=self.run_id,
                                                    task_goal=decision.reflection_prompt,
                                                    outcome="reflecting",
                                                )
                                            )
                                        except Exception as _exc:
                                            _logger.warning(
                                                "runner.reflect_context_inject_failed stage_id=%s error=%s",
                                                stage_id,
                                                _exc,
                                            )
                        except Exception as exc:
                            _logger.warning(
                                "runner.reflect_failed stage_id=%s error=%s",
                                stage_id,
                                exc,
                            )
                    else:
                        _logger.info(
                            "runner.reflect_no_orchestrator stage_id=%s",
                            stage_id,
                        )
                    # If a next attempt is scheduled (reflect-before-retry), run it now.
                    if decision.next_attempt_seq is not None:
                        _logger.info(
                            "runner.reflect_retry stage_id=%s next_attempt=%d",
                            stage_id,
                            decision.next_attempt_seq,
                        )
                        retry_result = self._execute_stage(stage_id)
                        if retry_result != "failed":
                            return retry_result
                        stage_result = retry_result
                        continue  # K-7: loop back instead of recursing
                    # Budget exhausted after reflection — do not propagate failure.
                    return "reflected"

                if decision.action == "escalate":
                    _logger.warning(
                        "runner.stage_escalated stage_id=%s run_id=%s",
                        stage_id,
                        self.run_id,
                    )
                    try:
                        self._record_event(
                            "StageEscalated",
                            {
                                "stage_id": stage_id,
                                "run_id": self.run_id,
                                "reason": decision.reason,
                            },
                        )
                    except Exception as exc:
                        _logger.warning(
                            "runner: StageEscalated event recording failed, continuing: %s", exc
                        )
                    return "failed"

                # action == "abort" or unknown
                _logger.info(
                    "runner.stage_aborted stage_id=%s run_id=%s",
                    stage_id,
                    self.run_id,
                )
                return "failed"

            _logger.warning(
                "runner.stage_failure_loop_ceiling stage_id=%s run_id=%s ceiling=%d",
                stage_id, self.run_id, _max_total_attempts,
            )
            return "failed"

        except GatePendingError:
            raise  # gate must propagate — not a retry failure

        except Exception as exc:
            _logger.warning(
                "runner.handle_stage_failure_error stage_id=%s error=%s — falling back to failed",
                stage_id,
                exc,
            )
            return "failed"

    def _get_attempt_history(self, stage_id: str) -> list:
        """Return prior attempt records for the given stage_id."""
        try:
            all_attempts = self._restart_policy._get_attempts(self.contract.task_id)
            return [a for a in all_attempts if getattr(a, "stage_id", None) == stage_id]
        except Exception:
            return []

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

    def _execute_remaining(self) -> RunResult:
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
        else:
            # Fallback: use stage_summaries (populated by _execute_stage on success).
            completed_stages = {
                sid
                for sid, summary in self.stage_summaries.items()
                if getattr(summary, "outcome", None) in ("completed", "success")
            }

        self._emit_observability("run_resumed", {
            "run_id": self.run_id,
            "completed_stages": sorted(completed_stages),
            "resuming_from": self.current_stage,
        })

        all_completed = True
        try:
            for stage_id in self.stage_graph.trace_order():
                if stage_id in completed_stages:
                    self._emit_observability("stage_skipped_resume", {
                        "run_id": self.run_id, "stage_id": stage_id,
                    })
                    continue

                all_completed = False
                stage_result = self._execute_stage(stage_id)
                if stage_result == "failed":
                    handled = self._handle_stage_failure(stage_id, stage_result)
                    if handled == "failed":
                        return self._finalize_run("failed")
                    # "reflected" or non-failed: continue to next stage
        except GatePendingError:
            raise  # gate must propagate during resume too

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
            profile_id=contract_data.get("profile_id", ""),  # J5-3: restore profile scoping
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
            base_dir = kwargs.get("raw_memory_base_dir", ".episodes")
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
        """Register a named human gate point on this run.

        The gate event is stored in ``_registered_gates`` (indexed by
        *gate_id*) and written into the session checkpoint so that a
        paused run can survive a process restart.

        Args:
            gate_id: Caller-assigned identifier for this gate.
            gate_type: Gate category — one of ``contract_correction``,
                ``route_direction``, ``artifact_review``,
                ``final_approval``.
            phase_name: Stage or phase at which the gate is registered.
            recommendation: Optional suggestion for the human reviewer.
            output_summary: Brief description of the work product.
        """
        from hi_agent.gate_protocol import GateEvent

        event = GateEvent(
            gate_id=gate_id,
            gate_type=gate_type,
            phase_name=phase_name,
            recommendation=recommendation,
            output_summary=output_summary,
        )
        self._registered_gates[gate_id] = event
        self._gate_pending = gate_id

        # Persist gate state into the session checkpoint so it survives
        # a process restart.
        if self.session is not None:
            try:
                self.session.events.append({
                    "event": "gate_registered",
                    "gate_id": gate_id,
                    "gate_type": gate_type,
                    "phase_name": phase_name,
                    "opened_at": event.opened_at,
                })
            except Exception as _exc:  # pragma: no cover
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.register_gate_session_failed",
                    _exc,
                    run_id=self.run_id,
                    gate_id=gate_id,
                )

        _logger.info(
            "runner.gate_registered run_id=%s gate_id=%s gate_type=%s phase=%s",
            self.run_id,
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
        """Resume execution after a human decision on a registered gate.

        Valid decisions: ``approved``, ``override``, ``backtrack``.

        The decision is logged to the run record via the event emitter
        and the session checkpoint.

        Args:
            gate_id: Gate to resume (must have been registered via
                :meth:`register_gate`).
            decision: Human decision — ``approved``, ``override``, or
                ``backtrack``.
            rationale: Free-text rationale for the decision.
        """
        _logger.info(
            "runner.gate_decision run_id=%s gate_id=%s decision=%s",
            self.run_id,
            gate_id,
            decision,
        )

        self._emit_observability("gate_decision", {
            "run_id": self.run_id,
            "gate_id": gate_id,
            "decision": decision,
            "rationale": rationale,
        })

        if self.session is not None:
            try:
                self.session.events.append({
                    "event": "gate_decision",
                    "gate_id": gate_id,
                    "decision": decision,
                    "rationale": rationale,
                })
            except Exception as _exc:  # pragma: no cover
                self._log_best_effort_exception(
                    logging.DEBUG,
                    "runner.resume_session_failed",
                    _exc,
                    run_id=self.run_id,
                    gate_id=gate_id,
                )

        # Unblock stage execution now that the human decision has been made.
        if self._gate_pending == gate_id:
            self._gate_pending = None
        if decision == "backtrack":
            self._run_terminated = True

    def continue_from_gate(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
    ) -> RunResult:
        """Resume execution after a human gate decision.

        This is the correct entry point after a :class:`GatePendingError` has
        been handled and a gate decision has been made. Calling ``execute()``
        directly after ``resume()`` re-executes all stages from the beginning;
        this method resumes from the first incomplete stage only.

        Args:
            gate_id: Gate identifier from the propagated ``GatePendingError``.
            decision: Human decision — ``"approved"``, ``"override"``, or
                ``"backtrack"``.
            rationale: Free-text rationale for the decision (optional).

        Returns:
            :class:`RunResult` with run outcome after completion.
        """
        self.resume(gate_id=gate_id, decision=decision, rationale=rationale)
        return self._execute_remaining()

    def continue_from_gate_graph(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
        *,
        last_stage: str | None = None,
        completed_stages: set[str] | None = None,
    ) -> RunResult:
        """Resume graph execution after a human gate decision.

        Unlike :meth:`continue_from_gate` which uses linear ``trace_order()``,
        this method resumes graph traversal from the correct position.

        Args:
            gate_id: Gate identifier from the propagated ``GatePendingError``.
            decision: Human decision — ``"approved"``, ``"override"``, or
                ``"backtrack"``.
            rationale: Free-text rationale for the decision (optional).
            last_stage: The stage that was executing when the gate fired.
                When None, uses ``self.current_stage``.
            completed_stages: Set of stage IDs already completed before the
                gate fired. When None, inferred from session.stage_states.

        Returns:
            :class:`RunResult` with run outcome after completion.
        """
        self.resume(gate_id=gate_id, decision=decision, rationale=rationale)

        if decision == "backtrack":
            return self._finalize_run("failed")

        # Determine which stages are already done.
        if completed_stages is None:
            if self.session is not None:
                completed_stages = {
                    sid for sid, state in self.session.stage_states.items()
                    if state == "completed"
                }
            else:
                completed_stages = set(self.stage_summaries.keys())

        # Resume graph traversal from last_stage's successors.
        start_stage = last_stage or self.current_stage
        if start_stage and start_stage not in completed_stages:
            # last_stage itself was not completed — retry it.
            current_stage: str | None = start_stage
        else:
            # Advance to successors not yet completed.
            successors = self.stage_graph.successors(start_stage) if start_stage else set()
            candidates = successors - completed_stages
            current_stage = self._select_next_stage(candidates) if candidates else None

        max_steps = len(self.stage_graph.transitions) * 2
        steps = 0
        try:
            while current_stage is not None and steps < max_steps:
                steps += 1
                if current_stage in completed_stages:
                    successors = self.stage_graph.successors(current_stage)
                    candidates = successors - completed_stages
                    current_stage = self._select_next_stage(candidates) if candidates else None
                    continue

                result = self._execute_stage(current_stage)
                if result == "failed":
                    backtrack = self.stage_graph.get_backtrack(current_stage)
                    if backtrack and backtrack not in completed_stages:
                        current_stage = backtrack
                        continue
                    handled = self._handle_stage_failure(current_stage, result)
                    if handled == "failed":
                        return self._finalize_run("failed")
                completed_stages.add(current_stage)

                successors = self.stage_graph.successors(current_stage)
                candidates = successors - completed_stages
                if not candidates:
                    break
                if len(candidates) > 1:
                    current_stage = self._select_next_stage(candidates)
                else:
                    current_stage = next(iter(candidates))
        except GatePendingError:
            raise
        except Exception as exc:
            self._log_best_effort_exception(
                logging.WARNING, "runner.continue_from_gate_graph_failed", exc,
                run_id=self.run_id, stage_id=self.current_stage,
            )
            return self._finalize_run("failed")

        return self._finalize_run("completed")

    # -----------------------------------------------------------------------
    # Sub-run delegation public API (Task 3 — P2-3)
    # -----------------------------------------------------------------------

    def dispatch_subrun(
        self,
        agent: str,
        profile_id: str,
        strategy: str = "sequential",
        restart_policy: str = "reflect(2)",
        goal: str = "",
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

        Returns:
            A :class:`SubRunHandle` with the child run identifier.

        Raises:
            RuntimeError: If no DelegationManager is configured.
        """
        import asyncio
        import uuid

        from hi_agent.task_mgmt.delegation import DelegationRequest

        if self._delegation_manager is None:
            raise RuntimeError(
                "dispatch_subrun requires a DelegationManager; "
                "inject one via RunExecutor(delegation_manager=...)"
            )

        task_id = f"{self.run_id}-sub-{uuid.uuid4().hex[:8]}"
        req = DelegationRequest(
            goal=goal or f"agent={agent}",
            task_id=task_id,
            config={
                "agent": agent,
                "profile_id": profile_id,
                "strategy": strategy,
                "restart_policy": restart_policy,
            },
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
            self._pending_subrun_futures[task_id] = future  # type: ignore[attr-defined]
        except RuntimeError:
            # No running loop — synchronous call path.
            results = asyncio.run(
                self._delegation_manager.delegate([req], parent_run_id=self.run_id)
            )
            self._completed_subrun_results[task_id] = results[0]  # type: ignore[attr-defined]

        return SubRunHandle(subrun_id=task_id, agent=agent)

    def await_subrun(self, handle: SubRunHandle) -> SubRunResult:
        """Wait for a dispatched sub-run and return its result.

        Args:
            handle: Handle returned by :meth:`dispatch_subrun`.

        Returns:
            A :class:`SubRunResult` with completion status and output.
        """
        import asyncio

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

                results = asyncio.run(_collect())

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
                    success=False, output="", error=None,
                    gate_id=getattr(dr, "gate_id", None), status="gate_pending",
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
                    success=False, output="", error=None,
                    gate_id=getattr(dr, "gate_id", None), status="gate_pending",
                )
            return SubRunResult(
                success=dr.status == "completed",
                output=dr.summary or dr.raw_output or "",
                error=dr.error,
            )

        _logger.warning(
            "runner.await_subrun_async_unknown_handle run_id=%s subrun_id=%s",
            self.run_id, subrun_id,
        )
        return SubRunResult(
            success=False, output="",
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
) -> AsyncRunResult:
    """Execute a RunExecutor using AsyncTaskScheduler and KernelFacade.

    This is a standalone async function (not a method) to avoid mutating
    the existing RunExecutor class interface. Call it as::

        result = await execute_async(executor, max_concurrency=8)

    .. warning::
        **Not wired into the server RunManager.** ``POST /runs`` dispatches
        ``executor.execute()`` (synchronous, linear), not this function.
        ``execute_async()`` returns :class:`AsyncRunResult` which has no
        ``status`` or ``stages`` fields and is incompatible with
        ``RunManager.to_dict()``. Use this function only for direct asyncio
        callers; do not surface it through the HTTP API without first
        adapting the result type to :class:`~hi_agent.contracts.requests.RunResult`.
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
    executor._run_id = run_id  # K-2: sync executor's run_id to match kernel registration
    executor._run_start_monotonic = time.monotonic()  # K-15: enable duration measurement
    # K-3: handles both sync and async kernels — only await if result is awaitable
    _start_result = executor.kernel.start_run(
        run_id=run_id,
        session_id=run_id,
        metadata={"goal": executor.contract.goal},
    )
    if inspect.isawaitable(_start_result):
        await _start_result

    # When the stage kernel (sync) differs from executor.kernel (async facade),
    # pre-register the run_id so open_branch / mark_branch_state can locate it.
    _sk = getattr(executor._stage_executor, "kernel", None)
    if _sk is not None and _sk is not executor.kernel and hasattr(_sk, "runs"):
        if run_id not in _sk.runs:
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
            import asyncio
            _stage_kernel = getattr(executor._stage_executor, "kernel", None)
            _sync_capable = _stage_kernel is not None and callable(
                getattr(_stage_kernel, "open_stage", None)
            ) and not inspect.iscoroutinefunction(
                getattr(_stage_kernel, "open_stage", None)
            )
            if _sync_capable:
                loop = asyncio.get_event_loop()
                try:
                    result = await loop.run_in_executor(
                        None, executor._execute_stage, node_id
                    )
                except Exception as _stage_exc:
                    from hi_agent.gate_protocol import GatePendingError as _GatePE
                    if isinstance(_stage_exc, _GatePE):
                        raise
                    result = "failed"
                status = "failed" if result == "failed" else "completed"
            else:
                # Async-only kernel (e.g. pure facade) — state is managed by
                # execute_turn; no sync stage methods available.
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
            _logger.warning(
                "execute_async: delegation failed for run_id=%s: %s", run_id, _exc
            )

    schedule_result = await scheduler.run(
        graph=graph,
        run_id=run_id,
        make_handler=make_handler,
    )

    # J3-3: Populate session.stage_states so a resumed run does not re-execute.
    if executor.session is not None:
        for node_id in schedule_result.completed_nodes:
            executor.session.stage_states[node_id] = "completed"

    # J3-2: Call _finalize_run for resource cleanup, L0→L3 memory chain, observability.
    outcome = "completed" if schedule_result.success else "failed"
    try:
        executor._finalize_run(outcome)
    except Exception as _fin_exc:
        _logger.warning("execute_async: _finalize_run failed: %s", _fin_exc)

    return AsyncRunResult(
        run_id=run_id,
        success=schedule_result.success,
        completed_nodes=schedule_result.completed_nodes,
    )
