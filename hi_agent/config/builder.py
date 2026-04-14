"""Factory that creates all TRACE subsystems from a single TraceConfig."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.harness.evidence_store import EvidenceStore, SqliteEvidenceStore
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine
from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.protocol import LLMGateway
from hi_agent.llm.registry import ModelRegistry
from hi_agent.llm.tier_router import TierAwareLLMGateway, TierRouter
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.orchestrator.task_orchestrator import TaskOrchestrator
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.kernel_facade_adapter import (
    KernelFacadeAdapter,
    create_local_adapter,
)
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import SkillRegistry
from hi_agent.observability.collector import MetricsCollector
from hi_agent.state import RunStateStore


class MissingCapabilityError(RuntimeError):
    """Raised when a profile's required capabilities are not registered."""


class SystemBuilder:
    """Factory that creates all TRACE subsystems from a single TraceConfig.

    This is the main assembly point -- creates properly configured
    instances of all subsystems and wires them together.
    """

    def __init__(
        self,
        config: TraceConfig | None = None,
        config_stack: Any | None = None,
        *,
        profile_registry: Any | None = None,
        capability_registry: Any | None = None,
        artifact_registry: Any | None = None,
    ) -> None:
        """Initialize SystemBuilder.

        Args:
            config: Optional TraceConfig. Defaults to a new TraceConfig().
            config_stack: Optional config stack (used by server wiring).
            profile_registry: Optional pre-built ProfileRegistry. When provided,
                build_profile_registry() returns it directly without creating a new one.
            capability_registry: Optional pre-built CapabilityRegistry. When provided,
                build_capability_registry() returns it directly without creating a new one.
            artifact_registry: Optional pre-built ArtifactRegistry. When provided,
                build_artifact_registry() returns it directly without creating a new one.
        """
        import threading as _threading
        self._config = config if config is not None else TraceConfig()
        self._stack = config_stack
        # Protects lazy singleton cache against concurrent build_executor() calls.
        # RLock (re-entrant) is required because several build_* methods acquire
        # this lock and then call other build_* methods that also acquire it
        # (e.g. build_capability_registry -> build_llm_gateway).
        self._singleton_lock = _threading.RLock()
        # Cache built singletons so repeated calls return the same instance.
        self._kernel: RuntimeAdapter | None = None
        self._llm_gateway: LLMGateway | None = None
        self._metrics_collector: MetricsCollector | None = None
        self._tier_router: Any | None = None  # cached alongside _llm_gateway
        self._run_context_manager: Any | None = None
        self._middleware_orchestrator: Any | None = None
        self._llm_budget_tracker: Any | None = None
        # Subsystem singletons — cached so readiness() and manifest reflect the
        # same instances used by actual run execution.
        self._skill_loader: Any | None = None
        self._mcp_registry: Any | None = None
        self._mcp_transport: Any | None = None
        self._plugin_loader: Any | None = None
        self._evidence_store: Any | None = None
        # Pre-inject registries if provided (allows derived builders to inherit state).
        # The build_*_registry() methods all use hasattr/is-None checks before creating
        # new instances, so pre-assigned values will be respected automatically.
        if profile_registry is not None:
            self._profile_registry = profile_registry
        if capability_registry is not None:
            self._capability_registry = capability_registry
        if artifact_registry is not None:
            self._artifact_registry = artifact_registry

        # Redirect deprecated TraceConfig fields to their successors before any
        # subsystem is built, so callers that set legacy fields get expected behavior.
        self._redirect_deprecated_config()
        # Warn about deprecated fields that have no successor (dead fields).
        self._config.validate_no_deprecated()

    def _redirect_deprecated_config(self) -> None:
        """Forward deprecated TraceConfig fields to their active successors.

        This preserves backward compatibility for callers that still set the old
        field names.  Only redirects when the successor field still holds its
        default value — explicit successor values always win.
        """
        cfg = self._config
        # default_model → openai_default_model (when successor is still the package default)
        if cfg.default_model != "gpt-4o" and cfg.openai_default_model == "gpt-4o":
            cfg.openai_default_model = cfg.default_model
        # llm_max_retries → llm_failover_max_retries
        if cfg.llm_max_retries != 2 and cfg.llm_failover_max_retries == 3:
            cfg.llm_failover_max_retries = cfg.llm_max_retries
        # harness_default_timeout → harness_action_default_timeout
        if cfg.harness_default_timeout != 60 and cfg.harness_action_default_timeout == 60:
            cfg.harness_action_default_timeout = cfg.harness_default_timeout
        # max_actions_per_run → task_budget_max_actions
        if cfg.max_actions_per_run != 100 and cfg.task_budget_max_actions == 50:
            cfg.task_budget_max_actions = cfg.max_actions_per_run
        # max_total_branches → cts_max_total_branches
        if cfg.max_total_branches != 20 and cfg.cts_max_total_branches == 20:
            cfg.cts_max_total_branches = cfg.max_total_branches
        # max_branches_per_stage → cts_max_active_branches_per_stage
        if cfg.max_branches_per_stage != 5 and cfg.cts_max_active_branches_per_stage == 3:
            cfg.cts_max_active_branches_per_stage = cfg.max_branches_per_stage

    # ------------------------------------------------------------------
    # Individual builders
    # ------------------------------------------------------------------

    def _build_run_context_manager(self) -> Any:
        """Build or return the shared RunContextManager singleton."""
        with self._singleton_lock:
            if self._run_context_manager is None:
                try:
                    from hi_agent.context.run_context import RunContextManager
                    self._run_context_manager = RunContextManager()
                    logger.info("_build_run_context_manager: RunContextManager created.")
                except Exception as exc:
                    logger.warning(
                        "_build_run_context_manager: failed to create RunContextManager: %s", exc
                    )
        return self._run_context_manager

    def _build_middleware_orchestrator(self) -> Any:
        """Build or return the shared MiddlewareOrchestrator singleton."""
        if self._middleware_orchestrator is None:
            try:
                from hi_agent.middleware.defaults import create_default_orchestrator
                gateway = self.build_llm_gateway()
                self._middleware_orchestrator = create_default_orchestrator(
                    llm_gateway=gateway,
                    quality_threshold=getattr(self._config, "gate_quality_threshold", 0.7),
                    summary_threshold=getattr(self._config, "perception_summary_threshold_tokens", 2000),
                    max_entities=getattr(self._config, "perception_max_entities", 50),
                    llm_summarize_char_threshold=getattr(self._config, "perception_summarize_char_threshold", 500),
                    summarize_temperature=getattr(self._config, "perception_summarize_temperature", 0.3),
                    summarize_max_tokens=getattr(self._config, "perception_summarize_max_tokens", 200),
                )
                logger.info(
                    "_build_middleware_orchestrator: MiddlewareOrchestrator created."
                )
            except Exception as exc:
                logger.warning(
                    "_build_middleware_orchestrator: failed to create MiddlewareOrchestrator: %s",
                    exc,
                )
        return self._middleware_orchestrator

    def _inject_middleware_dependencies(self, orchestrator: Any) -> None:
        """Post-inject subsystem dependencies into orchestrator's middleware instances.

        The orchestrator is created early — before context_manager, skill_loader,
        knowledge_manager, capability_invoker, and retrieval_engine are built — so
        those deps are None at construction time.  This method is called once all
        subsystems are available and patches the live middleware instances in-place.

        Only sets an attribute when it is currently None to avoid overwriting an
        intentionally injected value.
        """
        try:
            middlewares: dict[str, Any] = getattr(orchestrator, "_middlewares", {})
            if not middlewares:
                return

            # Resolve subsystems (cached: these methods return the same instance).
            context_mgr = self.build_context_manager()
            skill_ldr = self.build_skill_loader()
            knowledge_mgr = self.build_knowledge_manager()
            retrieval_eng = self.build_retrieval_engine()
            harness = self.build_harness()
            capability_inv = self.build_invoker()

            _ATTR_SUBSYSTEMS: list[tuple[str, Any]] = [
                ("_context_manager", context_mgr),
                ("_skill_loader", skill_ldr),
                ("_knowledge_manager", knowledge_mgr),
                ("_retrieval_engine", retrieval_eng),
                ("_harness_executor", harness),
                ("_capability_invoker", capability_inv),
            ]

            injected: list[str] = []
            for mw_name, mw in middlewares.items():
                for attr, value in _ATTR_SUBSYSTEMS:
                    if hasattr(mw, attr) and getattr(mw, attr) is None and value is not None:
                        setattr(mw, attr, value)
                        injected.append(f"{mw_name}.{attr}")

            if injected:
                logger.info(
                    "_inject_middleware_dependencies: injected into [%s].",
                    ", ".join(injected),
                )
        except Exception as exc:
            logger.warning(
                "_inject_middleware_dependencies: failed, middleware may run degraded: %s", exc
            )

    def _build_llm_budget_tracker(self) -> Any:
        """Build LLMBudgetTracker with config-driven limits."""
        try:
            from hi_agent.llm.budget_tracker import LLMBudgetTracker
            max_calls = getattr(self._config, "llm_budget_max_calls", 100)
            max_tokens = getattr(self._config, "llm_budget_max_tokens", 500_000)
            tracker = LLMBudgetTracker(max_calls=max_calls, max_tokens=max_tokens)
            logger.info(
                "_build_llm_budget_tracker: LLMBudgetTracker created "
                "(max_calls=%d, max_tokens=%d).",
                max_calls,
                max_tokens,
            )
            return tracker
        except Exception as exc:
            logger.warning(
                "_build_llm_budget_tracker: failed to create LLMBudgetTracker: %s", exc
            )
            return None

    def _build_restart_policy_engine(self) -> Any:
        """Build RestartPolicyEngine with no-op stub collaborators.

        The engine's collaborators (get_attempts, get_policy, update_state,
        record_attempt) are wired as no-op stubs so that the engine can be
        injected into RunExecutor without coupling the builder to a specific
        task registry implementation.
        """
        try:
            from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine, TaskRestartPolicy

            _default_policy = TaskRestartPolicy(
                max_attempts=2,
                backoff_base_ms=2000,
                on_exhausted="escalate",
            )
            # In-memory attempt store so the engine can actually track attempt history
            # and enforce max_attempts. Replaced by a persistent store when wired to
            # a real task registry.
            _attempt_store: dict[str, list[Any]] = {}
            _state_store: dict[str, Any] = {}
            engine = RestartPolicyEngine(
                get_attempts=lambda task_id: list(_attempt_store.get(task_id, [])),
                get_policy=lambda task_id: _default_policy,
                update_state=lambda task_id, state: _state_store.update({task_id: state}),
                record_attempt=lambda attempt: _attempt_store.setdefault(
                    getattr(attempt, "task_id", ""), []
                ).append(attempt),
            )
            logger.info("_build_restart_policy_engine: RestartPolicyEngine created with default policy (max_attempts=2, on_exhausted=escalate).")
            return engine
        except Exception as exc:
            logger.warning(
                "_build_restart_policy_engine: failed to create RestartPolicyEngine: %s", exc
            )
            return None

    def _build_reflection_orchestrator(self) -> Any:
        """Build ReflectionOrchestrator wired to the LLM gateway if available."""
        try:
            from hi_agent.task_mgmt.reflection import ReflectionOrchestrator
            from hi_agent.task_mgmt.reflection_bridge import ReflectionBridge

            gateway = self.build_llm_gateway()

            async def _inference_fn(**kwargs: Any) -> str:
                """LLM-backed or heuristic reflection inference."""
                import json as _json
                run_id = kwargs.get("run_id", "unknown")
                if gateway is None:
                    return _json.dumps({
                        "action": "retry_with_default",
                        "reason": "no LLM gateway available",
                        "run_id": run_id,
                    })
                try:
                    from hi_agent.llm.protocol import LLMRequest
                    recovery_context = kwargs.get("recovery_context", {})
                    prompt = (
                        f"Reflection for run {run_id}.\n"
                        f"Recovery context: {recovery_context}\n"
                        "Suggest a corrective action in one sentence."
                    )
                    req = LLMRequest(
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=256,
                    )
                    resp = gateway.complete(req)
                    return resp.content
                except Exception as exc:
                    logger.warning("_reflection_orchestrator inference_fn error: %s", exc)
                    return _json.dumps({
                        "action": "retry_with_default",
                        "reason": f"inference failed: {exc}",
                        "run_id": run_id,
                    })

            bridge = ReflectionBridge()
            orchestrator = ReflectionOrchestrator(
                bridge=bridge,
                inference_fn=_inference_fn,
            )
            logger.info("_build_reflection_orchestrator: ReflectionOrchestrator created.")
            return orchestrator
        except Exception as exc:
            logger.warning(
                "_build_reflection_orchestrator: failed to create ReflectionOrchestrator: %s",
                exc,
            )
            return None

    def build_metrics_collector(self) -> MetricsCollector:
        """Build or return the shared MetricsCollector singleton."""
        with self._singleton_lock:
            if self._metrics_collector is None:
                from hi_agent.observability.collector import default_alert_rules
                self._metrics_collector = MetricsCollector()
                for rule in default_alert_rules():
                    self._metrics_collector.add_alert_rule(rule)
                _webhook_url = os.environ.get("WEBHOOK_URL", "")
                if _webhook_url:
                    from hi_agent.observability.notification import (
                        build_notification_backend,
                        send_notification,
                    )
                    import time as _time
                    _backend = build_notification_backend(_webhook_url)

                    def _alert_cb(alert: object) -> None:
                        # alert is an Alert dataclass: rule_name, metric_name, current_value
                        _alert_name = getattr(alert, "rule_name", str(alert))
                        _metric_name = getattr(alert, "metric_name", "")
                        _value = getattr(alert, "current_value", 0.0)
                        send_notification(
                            backend=_backend,
                            event=f"alert.{_alert_name}",
                            severity="warning",
                            message=f"Alert {_alert_name}: {_metric_name}={_value:.3f}",
                            context={
                                "alert_name": _alert_name,
                                "metric_name": _metric_name,
                                "value": _value,
                            },
                            timestamp=_time.time(),
                        )

                    self._metrics_collector.set_alert_callback(_alert_cb)
        return self._metrics_collector

    def build_kernel(self) -> RuntimeAdapter:
        """Build kernel adapter.

        When ``config.kernel_base_url`` is set and is not ``"local"``,
        creates a :class:`KernelFacadeClient` in HTTP mode.
        Otherwise falls back to :func:`create_local_adapter` (in-process LocalFSM).
        """
        with self._singleton_lock:
            if self._kernel is None:
                base_url = self._config.kernel_base_url
                env = os.environ.get("HI_AGENT_ENV", "dev").lower()
                if base_url and base_url.lower() == "mock":
                    raise ValueError(
                        "kernel_base_url='mock' is no longer supported. "
                        "Use 'local' for in-process agent-kernel LocalFSM, "
                        "or set a real http(s) agent-kernel endpoint."
                    )
                if env == "prod" and (not base_url or base_url.lower() == "local"):
                    raise RuntimeError(
                        "Production mode requires a real agent-kernel HTTP endpoint. "
                        "Set kernel_base_url to http(s)://... and do not use 'local'."
                    )
                if base_url and base_url.lower() != "local":
                    self._kernel = KernelFacadeClient(
                        mode="http",
                        base_url=base_url,
                        timeout_seconds=30,
                    )
                else:
                    logger.warning(
                        "build_kernel: kernel_base_url=%r — using in-process LocalFSM. "
                        "Set kernel_base_url to a real agent-kernel HTTP endpoint for production.",
                        base_url,
                    )
                    self._kernel = create_local_adapter()
                # Wrap with resilience layer (retry + circuit breaker + event buffer).
                from hi_agent.runtime_adapter import ResilientKernelAdapter  # noqa: PLC0415
                self._kernel = ResilientKernelAdapter(
                    self._kernel,
                    max_retries=self._config.kernel_max_retries,
                )
        return self._kernel

    def _build_cache_injector(self) -> "Any | None":
        """Build PromptCacheInjector if prompt caching is enabled in config."""
        try:
            if not getattr(self._config, "prompt_cache_enabled", True):
                return None
            from hi_agent.llm.cache import PromptCacheConfig, PromptCacheInjector
            return PromptCacheInjector(
                PromptCacheConfig(
                    enabled=True,
                    anchor_messages=getattr(self._config, "prompt_cache_anchor_messages", 3),
                    min_cacheable_tokens=getattr(self._config, "prompt_cache_min_tokens", 1024),
                )
            )
        except Exception as exc:
            logger.warning("Failed to build PromptCacheInjector, caching disabled: %s", exc)
            return None

    def _build_failover_chain(self, base_url: str, default_model: str) -> "Any | None":
        """Build FailoverChain from env credential pool if failover is enabled."""
        try:
            if not getattr(self._config, "llm_failover_enabled", True):
                return None
            from hi_agent.llm.cache import PromptCacheConfig, PromptCacheInjector
            from hi_agent.llm.failover import (
                CredentialPool,
                FailoverChain,
                RetryPolicy,
                make_credential_pool_from_env,
            )
            from hi_agent.llm.http_gateway import HTTPGateway

            env_var = getattr(self._config, "llm_credential_pool_env_var", "ANTHROPIC_API_KEY")
            pool: CredentialPool = make_credential_pool_from_env(env_var=env_var)
            if pool.next_eligible() is None:
                logger.warning(
                    "_build_failover_chain: all credentials in cooldown, failover disabled."
                )
                return None

            timeout = float(getattr(self._config, "llm_timeout_seconds", 120))
            cache_injector = self._build_cache_injector()

            def _gateway_factory(api_key: str) -> HTTPGateway:
                return HTTPGateway(
                    base_url=base_url,
                    api_key=api_key,
                    timeout=timeout,
                    default_model=default_model,
                    max_retries=0,  # FailoverChain controls retries
                    cache_injector=cache_injector,
                )

            policy = RetryPolicy(
                max_retries=getattr(self._config, "llm_failover_max_retries", 3),
                base_delay_ms=getattr(self._config, "llm_failover_base_delay_ms", 500),
                max_delay_ms=getattr(self._config, "llm_failover_max_delay_ms", 30_000),
            )
            chain = FailoverChain(
                gateway_factory=_gateway_factory,
                pool=pool,
                policy=policy,
            )
            logger.info(
                "_build_failover_chain: FailoverChain created (max_retries=%d, pool_size=%d)",
                policy.max_retries,
                len(pool),
            )
            return chain
        except ValueError as exc:
            logger.info(
                "_build_failover_chain: credential pool unavailable (%s), failover disabled.", exc
            )
            return None
        except Exception as exc:
            logger.warning("Failed to build FailoverChain, failover disabled: %s", exc)
            return None

    def build_llm_gateway(self) -> LLMGateway | None:
        """Build LLM gateway -- auto-activates if API key found in env.

        Checks for known provider API keys in the environment and
        creates an :class:`HttpLLMGateway` for the first match.  When
        failover and/or prompt caching are enabled in config, the gateway
        is wired with :class:`FailoverChain` and :class:`PromptCacheInjector`.
        Returns ``None`` when no key is configured, which lets
        downstream subsystems fall back to heuristic behaviour.
        """
        with self._singleton_lock:
            if self._llm_gateway is not None:
                return self._llm_gateway

            for env_var, base_url, default_model in [
                (
                    self._config.openai_api_key_env,
                    self._config.openai_base_url,
                    self._config.openai_default_model,
                ),
                (
                    self._config.anthropic_api_key_env,
                    self._config.anthropic_base_url + "/v1",
                    self._config.anthropic_default_model,
                ),
            ]:
                if os.environ.get(env_var):
                    # Build optional cache injector and failover chain.
                    cache_injector = self._build_cache_injector()
                    failover_chain = self._build_failover_chain(base_url, default_model)

                    if self._llm_budget_tracker is None:
                        self._llm_budget_tracker = self._build_llm_budget_tracker()
                    raw_gateway: LLMGateway = HttpLLMGateway(
                        base_url=base_url,
                        api_key_env=env_var,
                        default_model=default_model,
                        timeout_seconds=self._config.llm_timeout_seconds,
                        failover_chain=failover_chain,
                        cache_injector=cache_injector,
                        budget_tracker=self._llm_budget_tracker,
                    )
                    registry = ModelRegistry()
                    registry.register_defaults()
                    tier_router = TierRouter(registry)
                    self._tier_router = tier_router
                    # Best-effort: apply cost-optimization overrides from any
                    # run history that the config exposes at startup time.
                    startup_history: list[dict[str, Any]] | None = getattr(
                        self._config, "startup_cost_history", None
                    )
                    self._wire_cost_optimizer(tier_router, startup_history)
                    self._llm_gateway = TierAwareLLMGateway(  # type: ignore[assignment]
                        raw_gateway, tier_router, registry
                    )
                    return self._llm_gateway

        is_prod = os.environ.get("HI_AGENT_ENV", "dev").lower() == "prod"
        if is_prod:
            raise RuntimeError(
                "Production mode requires real LLM credentials. "
                "Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
            )
        logger.warning(
            "build_llm_gateway: no API key found in environment "
            "(checked %s). LLM features will use heuristic fallback in non-prod mode. "
            "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable real LLM calls.",
            ", ".join([self._config.openai_api_key_env, self._config.anthropic_api_key_env]),
        )
        return None  # No API key found, LLM features disabled

    def _build_regression_detector(self) -> "RegressionDetector":
        """Build RegressionDetector with optional persistent storage."""
        from hi_agent.evolve.regression_detector import RegressionDetector

        storage_path = self._config.episodic_storage_dir.replace(
            "episodes", "regression_data.json"
        )
        detector = RegressionDetector(
            baseline_window=self._config.evolve_regression_window,
            threshold=self._config.evolve_regression_threshold,
            storage_path=storage_path,
        )
        try:
            detector.load()
        except Exception as exc:  # pragma: no cover
            import logging
            logging.getLogger(__name__).debug("RegressionDetector.load skipped: %s", exc)
        return detector

    def build_evolve_engine(self) -> EvolveEngine:
        """Build EvolveEngine with config-driven parameters."""
        from hi_agent.evolve.champion_challenger import ChampionChallenger
        from hi_agent.evolve.skill_extractor import SkillExtractor

        gateway = self.build_llm_gateway()
        return EvolveEngine(
            llm_gateway=gateway,
            skill_extractor=SkillExtractor(
                min_confidence=self._config.evolve_min_confidence,
                gateway=gateway,
            ),
            regression_detector=self._build_regression_detector(),
            champion_challenger=ChampionChallenger(),
            version_manager=self.build_skill_version_manager(),
        )

    def build_invoker(self) -> Any:
        """Build a CapabilityInvoker using the SHARED capability registry singleton.

        IMPORTANT: Uses self.build_capability_registry() — the same registry instance
        that _validate_required_capabilities() checks. Any capability registered via
        builder.build_capability_registry().register(...) is immediately available
        to the harness executor.
        """
        from hi_agent.capability.circuit_breaker import CircuitBreaker  # noqa: PLC0415
        from hi_agent.capability.invoker import CapabilityInvoker  # noqa: PLC0415

        registry = self.build_capability_registry()  # shared singleton — NOT a fresh CapabilityRegistry()
        if registry is None:
            # Registry construction failed — create a minimal empty registry so
            # the invoker is never constructed with None, preventing AttributeError
            # downstream. The invoker will be usable but have no capabilities.
            from hi_agent.capability.registry import CapabilityRegistry  # noqa: PLC0415
            registry = CapabilityRegistry()
            logger.warning("build_invoker: registry is None, using empty fallback registry.")
        breaker = CircuitBreaker()
        invoker = CapabilityInvoker(registry=registry, breaker=breaker)
        logger.info(
            "build_invoker: using shared registry with %d capabilities.",
            len(registry.list_names()),
        )
        return invoker

    def build_capability_registry(self) -> Any:
        """Build or return the shared CapabilityRegistry singleton.

        Business agents can register capabilities into this registry before
        calling :meth:`build_executor`.  The same registry instance is used
        by :meth:`_validate_required_capabilities` and :meth:`build_invoker`.
        """
        with self._singleton_lock:
            if not hasattr(self, "_capability_registry") or self._capability_registry is None:
                try:
                    from hi_agent.capability.defaults import register_default_capabilities  # noqa: PLC0415
                    from hi_agent.capability.registry import CapabilityRegistry  # noqa: PLC0415
                    from hi_agent.capability.tools import register_builtin_tools  # noqa: PLC0415
                    registry = CapabilityRegistry()
                    gateway = self.build_llm_gateway()
                    try:
                        register_default_capabilities(registry, llm_gateway=gateway)
                    except Exception as exc:
                        logger.warning(
                            "build_capability_registry: register_default_capabilities failed (%s); "
                            "registry will have no pre-registered capabilities.",
                            exc,
                        )
                    register_builtin_tools(registry)
                    self._capability_registry = registry
                    logger.info(
                        "build_capability_registry: CapabilityRegistry created with %d capabilities.",
                        len(registry.list_names()),
                    )
                except Exception as exc:
                    logger.warning("build_capability_registry: failed: %s", exc)
                    self._capability_registry = None
        return self._capability_registry

    def build_artifact_registry(self) -> Any:
        """Build or return the shared ArtifactRegistry singleton."""
        if not hasattr(self, "_artifact_registry") or self._artifact_registry is None:
            try:
                from hi_agent.artifacts.registry import ArtifactRegistry  # noqa: PLC0415
                self._artifact_registry = ArtifactRegistry()
                logger.info("build_artifact_registry: ArtifactRegistry created.")
            except Exception as exc:
                logger.warning("build_artifact_registry: failed: %s", exc)
                self._artifact_registry = None
        return self._artifact_registry

    def build_mcp_registry(self) -> Any:
        """Build or return the shared MCPRegistry singleton."""
        with self._singleton_lock:
            if self._mcp_registry is None:
                try:
                    from hi_agent.mcp.registry import MCPRegistry  # noqa: PLC0415
                    self._mcp_registry = MCPRegistry()
                    logger.info("build_mcp_registry: MCPRegistry created.")
                except Exception as exc:
                    logger.warning("build_mcp_registry: failed: %s", exc)
                    self._mcp_registry = None
        return self._mcp_registry

    def build_mcp_transport(self) -> Any:
        """Build or return the shared MultiStdioTransport singleton.

        Returns a ``MultiStdioTransport`` when MCP servers are registered with
        ``transport="stdio"``, otherwise returns ``None``.  The transport is
        passed to ``MCPBinding`` so that registered tools become invokable.
        """
        with self._singleton_lock:
            if self._mcp_transport is not None:
                return self._mcp_transport
            registry = self.build_mcp_registry()
            if registry is None:
                return None
            stdio_servers = [
                s for s in registry.list_servers()
                if s.get("transport") == "stdio"
            ]
            if not stdio_servers:
                logger.debug("build_mcp_transport: no stdio MCP servers registered; transport not created.")
                return None
            try:
                from hi_agent.mcp.transport import MultiStdioTransport  # noqa: PLC0415
                self._mcp_transport = MultiStdioTransport(mcp_registry=registry)
                logger.info(
                    "build_mcp_transport: MultiStdioTransport created for %d stdio server(s).",
                    len(stdio_servers),
                )
            except Exception as exc:
                logger.warning("build_mcp_transport: failed: %s", exc)
                self._mcp_transport = None
        return self._mcp_transport

    def build_harness(self, capability_invoker: Any | None = None) -> HarnessExecutor:
        """Build HarnessExecutor with config-driven governance.

        Args:
            capability_invoker: Optional pre-built CapabilityInvoker. When None,
                a real invoker is created via :meth:`build_invoker` so that
                ``HarnessExecutor._dispatch()`` never raises ``RuntimeError``.
        """
        governance = GovernanceEngine()
        if self._config.evidence_store_backend == "sqlite":
            with self._singleton_lock:
                if self._evidence_store is None:
                    self._evidence_store = SqliteEvidenceStore(
                        db_path=self._config.evidence_store_path
                    )
            evidence_store: EvidenceStore | SqliteEvidenceStore = self._evidence_store
        else:
            logger.warning(
                "build_harness: evidence_store_backend=%r — using in-memory store. "
                "Evidence will not persist across restarts. "
                "Set evidence_store_backend='sqlite' for production.",
                self._config.evidence_store_backend,
            )
            evidence_store = EvidenceStore()
        if capability_invoker is None:
            capability_invoker = self.build_invoker()
        return HarnessExecutor(
            governance=governance,
            evidence_store=evidence_store,
            capability_invoker=capability_invoker,
            artifact_registry=self.build_artifact_registry(),
        )

    def build_skill_registry(self) -> SkillRegistry:
        """Build SkillRegistry using configured storage directory."""
        return SkillRegistry(storage_dir=self._config.skill_storage_dir)

    def build_skill_loader(self) -> Any:
        """Build or return the shared SkillLoader singleton.

        Search order (highest to lowest priority):
        1. Built-in skills bundled with hi-agent (hi_agent/skills/builtin/)
        2. User-global skills (~/.hi_agent/skills/)
        3. Project-local skills (config.skill_storage_dir, default .hi_agent/skills/)
        """
        if self._skill_loader is not None:
            return self._skill_loader

        import pathlib
        from hi_agent.skill.loader import SkillLoader

        builtin_dir = str(pathlib.Path(__file__).parent.parent / "skills" / "builtin")
        user_global_dir = str(pathlib.Path.home() / ".hi_agent" / "skills")
        project_dir = self._config.skill_storage_dir

        # Deduplicate while preserving order
        seen: set[str] = set()
        dirs: list[str] = []
        for d in [builtin_dir, user_global_dir, project_dir]:
            if d not in seen:
                seen.add(d)
                dirs.append(d)

        self._skill_loader = SkillLoader(
            search_dirs=dirs,
            max_skills_in_prompt=self._config.skill_loader_max_skills_in_prompt,
            max_prompt_tokens=self._config.skill_loader_max_prompt_tokens,
        )
        return self._skill_loader

    def build_plugin_loader(self) -> Any:
        """Build or return the shared PluginLoader singleton.

        Loads and activates plugins from the default plugin directories
        (.hi_agent/plugins, ~/.hi_agent/plugins). Returns the cached singleton
        on subsequent calls so the same instance is shared across server
        endpoints and executor builds.
        """
        if self._plugin_loader is None:
            from hi_agent.plugin.loader import PluginLoader  # noqa: PLC0415
            self._plugin_loader = PluginLoader()
            self._plugin_loader.load_all()
            activated = self._plugin_loader.activate_all()
            if activated:
                logger.info("build_plugin_loader: activated %d plugin(s).", activated)
        return self._plugin_loader

    def _wire_plugin_contributions(self) -> None:
        """Wire plugin manifest declarations (skill_dirs, mcp_servers) into live subsystems.

        Called once after all subsystems are built so plugins can extend the
        platform without requiring restart. Capability declarations are logged
        but not auto-registered (require entry_point execution).
        """
        if self._plugin_loader is None:
            return
        for manifest in self._plugin_loader._loaded.values():
            if manifest.status != "active":
                continue
            plugin_dir = manifest.plugin_dir or ""

            # Wire skill_dirs into the SkillLoader search paths.
            if manifest.skill_dirs and self._skill_loader is not None:
                import os  # noqa: PLC0415
                for skill_dir in manifest.skill_dirs:
                    resolved = os.path.join(plugin_dir, skill_dir) if plugin_dir else skill_dir
                    search_dirs = getattr(self._skill_loader, "_search_dirs", [])
                    if resolved not in search_dirs:
                        try:
                            search_dirs.append(resolved)
                            self._skill_loader.load_dir(resolved, source=f"plugin:{manifest.name}")
                            logger.info(
                                "_wire_plugin_contributions: loaded skills from %r (plugin %r).",
                                resolved, manifest.name,
                            )
                        except Exception as exc:
                            logger.warning(
                                "_wire_plugin_contributions: could not load skill_dir %r: %s",
                                resolved, exc,
                            )

            # Register mcp_servers into MCPRegistry.
            if manifest.mcp_servers and self._mcp_registry is not None:
                for srv_cfg in manifest.mcp_servers:
                    srv_name = srv_cfg.get("name", manifest.name)
                    srv_id = srv_cfg.get("id", f"{manifest.name}:{srv_name}")
                    try:
                        self._mcp_registry.register(
                            server_id=srv_id,
                            name=srv_name,
                            transport=srv_cfg.get("transport", "stdio"),
                            endpoint=srv_cfg.get("endpoint", ""),
                            tools=srv_cfg.get("tools"),
                        )
                        logger.info(
                            "_wire_plugin_contributions: registered MCP server %r from plugin %r.",
                            srv_name, manifest.name,
                        )
                    except Exception as exc:
                        logger.warning(
                            "_wire_plugin_contributions: failed to register MCP server %r: %s",
                            srv_name, exc,
                        )

            # Log declared capabilities (actual handler registration requires entry_point).
            if manifest.capabilities:
                logger.info(
                    "_wire_plugin_contributions: plugin %r declares capabilities %s; "
                    "set entry_point to auto-register handlers.",
                    manifest.name, manifest.capabilities,
                )

        # After all plugin MCP servers are registered, (re-)build the transport
        # and close the provider circuit by calling MCPBinding.bind_all().
        if self._mcp_registry is not None:
            stdio_count = sum(
                1 for s in self._mcp_registry.list_servers()
                if s.get("transport") == "stdio"
            )
            if stdio_count > 0 and self._mcp_transport is None:
                self.build_mcp_transport()
            # Probe every declared server before binding.  Only servers that
            # pass a real JSON-RPC initialize handshake are promoted to
            # "healthy"; unreachable servers stay "registered" and are tracked
            # as unavailable in MCPBinding.bind_all().
            if self._mcp_transport is not None:
                try:
                    from hi_agent.mcp.health import MCPHealth  # noqa: PLC0415
                    _hc = MCPHealth(self._mcp_registry, transport=self._mcp_transport)
                    _hc.check_all()
                    logger.debug("_wire_plugin_contributions: MCP health probe completed.")
                except Exception as _hc_exc:
                    logger.warning(
                        "_wire_plugin_contributions: MCP health probe failed: %s", _hc_exc
                    )
            # Wire external MCP tools into CapabilityRegistry so they are
            # invokable as standard capabilities.  This closes the circuit:
            # register → health-check → bind → capability.
            if self._mcp_transport is not None:
                try:
                    from hi_agent.mcp.binding import MCPBinding  # noqa: PLC0415
                    cap_registry = self.build_capability_registry()
                    mcp_reg = self.build_mcp_registry()
                    _binding = MCPBinding(
                        registry=cap_registry,
                        mcp_registry=mcp_reg,
                        transport=self._mcp_transport,
                    )
                    _bound = _binding.bind_all()
                    logger.info(
                        "_wire_plugin_contributions: MCPBinding.bind_all() registered %d MCP tool(s).",
                        _bound,
                    )
                except Exception as _mcp_exc:
                    logger.warning(
                        "_wire_plugin_contributions: MCPBinding.bind_all() failed: %s", _mcp_exc
                    )

    def build_skill_observer(self) -> Any:
        """Build SkillObserver for execution telemetry."""
        from hi_agent.skill.observer import SkillObserver

        return SkillObserver(
            storage_dir=self._config.skill_storage_dir + "/observations"
        )

    def build_skill_version_manager(self) -> Any:
        """Build SkillVersionManager for champion/challenger versioning."""
        from hi_agent.skill.version import SkillVersionManager

        mgr = SkillVersionManager(
            storage_dir=self._config.skill_storage_dir + "/versions"
        )
        try:
            mgr.load()
        except (FileNotFoundError, KeyError, ValueError):
            pass  # no prior state on first run — expected on fresh installs
        return mgr

    def build_skill_evolver(self) -> Any:
        """Build or return the shared SkillEvolver singleton.

        Cached so that the internal _runs_since_evolve counter persists across
        per-request RunExecutor instances; otherwise the interval counter resets
        to 0 on every request and evolve_cycle() never fires.
        """
        if getattr(self, "_skill_evolver", None) is not None:
            return self._skill_evolver
        from hi_agent.skill.evolver import SkillEvolver

        observer = self.build_skill_observer()
        version_mgr = self.build_skill_version_manager()
        gateway = self.build_llm_gateway()
        self._skill_evolver = SkillEvolver.from_config(
            cfg=self._config,
            llm_gateway=gateway,
            observer=observer,
            version_manager=version_mgr,
        )
        return self._skill_evolver

    def build_episodic_store(self) -> EpisodicMemoryStore:
        """Build EpisodicMemoryStore using configured storage directory."""
        return EpisodicMemoryStore(storage_dir=self._config.episodic_storage_dir)

    def build_failure_collector(self) -> FailureCollector:
        """Build a fresh FailureCollector."""
        return FailureCollector()

    def build_watchdog(self) -> ProgressWatchdog:
        """Build ProgressWatchdog with config-driven thresholds."""
        return ProgressWatchdog(
            window_size=self._config.watchdog_window_size,
            min_success_rate=self._config.watchdog_min_success_rate,
            max_consecutive_failures=self._config.watchdog_max_consecutive_failures,
        )

    # ------------------------------------------------------------------
    # Memory tier builders
    # ------------------------------------------------------------------

    def build_short_term_store(self) -> Any:
        """Build short-term memory store."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        return ShortTermMemoryStore(
            self._config.episodic_storage_dir.replace("episodes", "short_term")
        )

    def build_mid_term_store(self) -> Any:
        """Build mid-term memory store."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        return MidTermMemoryStore(
            self._config.episodic_storage_dir.replace("episodes", "mid_term")
        )

    def build_long_term_graph(self) -> Any:
        """Build long-term memory graph."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        graph = LongTermMemoryGraph(
            self._config.episodic_storage_dir.replace(
                "episodes", "long_term/graph.json"
            )
        )
        try:
            graph.load()
        except (FileNotFoundError, KeyError, ValueError):
            pass  # no prior state on first run — expected on fresh installs
        return graph

    def build_retrieval_engine(self) -> Any:
        """Build four-layer retrieval engine across all memory tiers.

        Layer 4 (semantic embedding re-ranking) is activated by wiring a
        TFIDFEmbeddingProvider against the engine's internal TFIDFIndex.
        This requires no external dependencies.  If construction fails for
        any reason the engine falls back to embedding_fn=None (Layers 1-3
        only).
        """
        from hi_agent.knowledge.retrieval_engine import RetrievalEngine

        wiki = self.build_knowledge_wiki()
        graph = self.build_long_term_graph()
        short = self.build_short_term_store()
        mid = self.build_mid_term_store()

        # Build the engine first so we can access its internal _tfidf index.
        engine = RetrievalEngine(
            wiki=wiki, graph=graph, short_term=short, mid_term=mid
        )

        # Activate Layer 4 by wiring in a TF-IDF-based embedding function.
        try:
            from hi_agent.knowledge.embedding import TFIDFEmbeddingProvider  # noqa: PLC0415

            provider = TFIDFEmbeddingProvider(engine._tfidf)
            engine._embedding_fn = provider.as_callable()
        except Exception:  # noqa: BLE001
            # Graceful degradation: Layer 4 stays disabled, Layers 1-3 work normally.
            pass

        return engine

    def build_memory_lifecycle_manager(self) -> MemoryLifecycleManager:
        """Build MemoryLifecycleManager wiring all memory tiers."""
        return MemoryLifecycleManager(
            short_term_store=self.build_short_term_store(),
            mid_term_store=self.build_mid_term_store(),
            long_term_graph=self.build_long_term_graph(),
            retrieval_engine=self.build_retrieval_engine(),
        )

    # ------------------------------------------------------------------
    # Knowledge tier builders
    # ------------------------------------------------------------------

    def build_knowledge_wiki(self) -> Any:
        """Build KnowledgeWiki for wiki-based knowledge storage."""
        from hi_agent.knowledge.wiki import KnowledgeWiki

        base = self._config.episodic_storage_dir.replace("episodes", "")
        wiki = KnowledgeWiki(os.path.join(base, "knowledge", "wiki"))
        try:
            wiki.load()
        except (FileNotFoundError, KeyError, ValueError):
            pass  # no prior state on first run — expected on fresh installs
        except Exception as exc:
            logger.warning("build_wiki: failed to load prior wiki state: %s", exc)
        return wiki

    def build_user_knowledge_store(self) -> Any:
        """Build UserKnowledgeStore for user profile knowledge."""
        from hi_agent.knowledge.user_knowledge import UserKnowledgeStore

        base = self._config.episodic_storage_dir.replace("episodes", "")
        return UserKnowledgeStore(os.path.join(base, "knowledge", "user"))

    def build_knowledge_manager(self) -> Any:
        """Build KnowledgeManager wiring wiki, user store, graph, and renderer."""
        from hi_agent.knowledge.graph_renderer import GraphRenderer
        from hi_agent.knowledge.knowledge_manager import KnowledgeManager

        wiki = self.build_knowledge_wiki()
        user_store = self.build_user_knowledge_store()
        graph = self.build_long_term_graph()
        renderer = GraphRenderer(graph)
        return KnowledgeManager(
            wiki=wiki, user_store=user_store, graph=graph, renderer=renderer,
        )

    # ------------------------------------------------------------------
    # Composite builders
    # ------------------------------------------------------------------

    def _build_compressor(self) -> MemoryCompressor:
        """Create MemoryCompressor, wiring LLM gateway if available."""
        return MemoryCompressor(
            gateway=self.build_llm_gateway(),
            compress_threshold=self._config.memory_compress_threshold,
            timeout_s=self._config.memory_compress_timeout_seconds,
            fallback_items=self._config.memory_compress_fallback_items,
            max_findings=self._config.memory_compress_max_findings,
            max_decisions=self._config.memory_compress_max_decisions,
            max_entities=self._config.memory_compress_max_entities,
            max_tokens=self._config.memory_compress_max_tokens,
        )

    def build_profile_registry(self) -> Any:
        """Build or return the platform ProfileRegistry singleton.

        Business agents register their ProfileSpec instances into this registry
        before submitting runs.  The SystemBuilder reads from it during
        executor construction when a ``profile_id`` is present on the contract.
        """
        if not hasattr(self, "_profile_registry") or self._profile_registry is None:
            try:
                from hi_agent.profiles.registry import ProfileRegistry  # noqa: PLC0415
                self._profile_registry = ProfileRegistry()
                logger.info("build_profile_registry: ProfileRegistry created.")
            except Exception as exc:
                logger.warning("build_profile_registry: failed: %s", exc)
                self._profile_registry = None
        return self._profile_registry

    def register_profile(self, spec: Any) -> None:
        """Register a ProfileSpec with this builder's ProfileRegistry.

        Upper-layer packages should call this to register profiles without
        relying on builder internals::

            builder = SystemBuilder()
            builder.register_profile(build_rnd_profile_spec())
            executor = builder.build_executor(contract)
        """
        self.build_profile_registry().register(spec)

    def _validate_required_capabilities(self, resolved_profile: Any) -> None:
        """Raise MissingCapabilityError if required capabilities are not registered."""
        try:
            registry = self.build_capability_registry()
            registered = set(registry.list_names()) if hasattr(registry, "list_names") else set()
        except Exception:
            registered = set()

        required = set(resolved_profile.required_capabilities)
        missing = required - registered
        if missing:
            raise MissingCapabilityError(
                f"Profile '{resolved_profile.profile_id}' requires capabilities that are not "
                f"registered: {sorted(missing)}. "
                f"Register them via CapabilityRegistry before building the executor."
            )

    def _resolve_profile(self, profile_id: str | None) -> Any:
        """Resolve a profile_id to a ResolvedProfile, or None for TRACE defaults."""
        if not profile_id:
            return None
        try:
            from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver  # noqa: PLC0415
            registry = self.build_profile_registry()
            if registry is None:
                return None
            return ProfileRuntimeResolver(registry).resolve(profile_id)
        except Exception as exc:
            logger.warning("_resolve_profile: failed for %r: %s", profile_id, exc)
            return None

    def _build_route_engine(self, stage_actions: dict | None = None) -> HybridRouteEngine:
        """Create HybridRouteEngine with LLM gateway + SkillMatcher if available.

        Args:
            stage_actions: Optional stage→capability mapping from a profile.
                When provided, the internal RuleRouteEngine uses these actions
                instead of the TRACE sample defaults.
        """
        from hi_agent.route_engine.rule_engine import RuleRouteEngine  # noqa: PLC0415

        registry = self.build_skill_registry()
        gateway = self.build_llm_gateway()
        matcher = SkillMatcher(registry=registry) if registry else None
        rule_engine = RuleRouteEngine(
            skill_matcher=matcher,
            stage_actions=stage_actions,  # None → TRACE ClassVar defaults
        )
        return HybridRouteEngine(
            rule_engine=rule_engine,
            gateway=gateway,
            skill_matcher=matcher,
            confidence_threshold=self._config.route_confidence_threshold,
        )

    def _build_skill_recorder(self) -> SkillUsageRecorder:
        """Create SkillUsageRecorder with the skill registry."""
        return SkillUsageRecorder(registry=self.build_skill_registry())

    def build_context_manager(
        self,
        session: Any = None,
        memory_retriever: Any = None,
        skill_loader: Any = None,
        compressor: Any = None,
    ) -> Any:
        """Build ContextManager with config-driven budget and threshold wiring."""
        from hi_agent.context.manager import ContextManager

        if compressor is None:
            compressor = self._build_compressor()
        if skill_loader is None and hasattr(self, "build_skill_loader"):
            skill_loader = self.build_skill_loader()
        return ContextManager.from_config(
            self._config,
            session=session,
            memory_retriever=memory_retriever,
            skill_loader=skill_loader,
            compressor=compressor,
        )

    def build_budget_guard(self, total_budget_tokens: int | None = None) -> Any:
        """Build BudgetGuard with config-driven total token budget."""
        from hi_agent.task_mgmt.budget_guard import BudgetGuard

        budget = total_budget_tokens or self._config.llm_budget_max_tokens
        return BudgetGuard.from_config(self._config, total_budget_tokens=budget)

    def _wire_cost_optimizer(
        self,
        tier_router: Any,
        run_history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Apply cost optimization hints to tier_router based on run history.

        Reads aggregate telemetry from *run_history* (a list of cost-summary
        dicts each with ``"total_usd"`` and ``"per_model"`` keys), generates
        rule-based :class:`~hi_agent.session.cost_optimizer.CostOptimizationHint`
        objects, converts them to tier overrides via
        :func:`~hi_agent.session.cost_optimizer.derive_tier_overrides`, and
        applies them to *tier_router* in one shot so that the **very first**
        run after startup already benefits from prior cost telemetry.

        All errors are swallowed; this method must never break normal startup.
        """
        if not run_history:
            return
        try:
            from hi_agent.session.cost_optimizer import (
                derive_tier_overrides,
                recommend_cost_optimizations,
            )

            total_usd = sum(r.get("total_usd", 0.0) for r in run_history)
            avg_cost = total_usd / len(run_history)
            merged_per_model: dict[str, float] = {}
            for r in run_history:
                for model, cost in r.get("per_model", {}).items():
                    merged_per_model[model] = merged_per_model.get(model, 0.0) + cost

            hints = recommend_cost_optimizations(
                run_count=len(run_history),
                avg_cost_per_run=avg_cost,
                per_model_breakdown=merged_per_model,
            )
            overrides = derive_tier_overrides(hints)
            if overrides and hasattr(tier_router, "apply_cost_overrides"):
                tier_router.apply_cost_overrides(overrides)
                logger.info(
                    "Cost optimizer applied %d overrides at startup: %s",
                    len(overrides),
                    overrides,
                )
        except Exception as exc:
            logger.warning("Cost optimizer wiring failed: %s", exc)

    def _build_delegation_manager(self) -> Any:
        """Build DelegationManager with config-driven concurrency and polling parameters.

        Wires the shared kernel adapter and async LLM gateway (for result
        summarization) so that child runs can be spawned and their outputs
        compressed before injection into the parent context window.
        """
        try:
            from hi_agent.task_mgmt.delegation import DelegationConfig, DelegationManager
            from hi_agent.llm.http_gateway import HTTPGateway

            config = DelegationConfig(
                max_concurrent=getattr(
                    self._config, "delegation_max_concurrent", 3
                ),
                poll_interval_seconds=getattr(
                    self._config, "delegation_poll_interval_seconds", 2.0
                ),
                summary_max_chars=getattr(
                    self._config, "delegation_summary_max_chars", 2000
                ),
            )
            kernel = self.build_kernel()

            # Attempt to get an async LLM gateway for child-run summarization.
            # Falls back to None (truncation-only mode) when unavailable.
            # Wraps HTTPGateway with TierAwareLLMGateway.acomplete() so that
            # async callers also benefit from tier routing and budget management.
            async_llm: Any | None = None
            try:
                from hi_agent.llm.http_gateway import HTTPGateway as _HTTPGateway
                import os as _os

                for env_var, base_url, default_model in [
                    (
                        self._config.openai_api_key_env,
                        self._config.openai_base_url,
                        self._config.openai_default_model,
                    ),
                    (
                        self._config.anthropic_api_key_env,
                        self._config.anthropic_base_url + "/v1",
                        self._config.anthropic_default_model,
                    ),
                ]:
                    if _os.environ.get(env_var):
                        _http_gw = _HTTPGateway(
                            base_url=base_url,
                            api_key=_os.environ[env_var],
                            default_model=default_model,
                            timeout=float(
                                getattr(self._config, "llm_timeout_seconds", 120)
                            ),
                        )
                        # Wrap with TierAwareLLMGateway so async callers
                        # go through tier routing (TierAwareLLMGateway now
                        # implements acomplete() for the AsyncLLMGateway surface).
                        _sync_gw = self.build_llm_gateway()
                        if _sync_gw is not None and hasattr(_sync_gw, "_tier_router"):
                            async_llm = TierAwareLLMGateway(
                                inner=_http_gw,
                                tier_router=_sync_gw._tier_router,  # type: ignore[union-attr]
                                registry=_sync_gw._registry,  # type: ignore[union-attr]
                            )
                        else:
                            async_llm = _http_gw
                        break
            except Exception as _exc:
                logger.debug(
                    "_build_delegation_manager: async LLM gateway unavailable (%s), "
                    "child-run summaries will be truncated.",
                    _exc,
                )

            manager = DelegationManager(
                kernel=kernel,
                config=config,
                llm=async_llm,
            )
            logger.info(
                "_build_delegation_manager: DelegationManager created "
                "(max_concurrent=%d, poll_interval=%.1fs).",
                config.max_concurrent,
                config.poll_interval_seconds,
            )
            return manager
        except Exception as exc:
            logger.warning(
                "_build_delegation_manager: failed to create DelegationManager: %s", exc
            )
            return None

    def _resolve_with_patch(self, patch: dict) -> "TraceConfig":
        """Return a new TraceConfig with *patch* merged over self._config.

        When a ConfigStack is available, delegates to it so that all five
        config layers (defaults → file → profile → env → run patch) are
        honoured.  Falls back to a simple merge over the cached config
        otherwise.
        """
        if self._stack is not None:
            return self._stack.resolve(run_patch=patch)
        from dataclasses import asdict, fields as dc_fields
        from hi_agent.config.profile import deep_merge
        base = asdict(self._config)
        merged = deep_merge(base, patch)
        known = {f.name for f in dc_fields(TraceConfig)}
        return TraceConfig(**{k: v for k, v in merged.items() if k in known})

    def _build_executor_impl(
        self, contract: TaskContract, resolved_profile: Any = None
    ) -> RunExecutor:
        """Build a fully-wired RunExecutor for a given task contract.

        Args:
            contract: Task contract.
            resolved_profile: Optional ``ResolvedProfile`` from the platform
                ProfileRegistry.  When provided, its stage_graph, stage_actions,
                and evaluator override the TRACE sample defaults.
        """
        km = self.build_knowledge_manager()
        invoker = self.build_invoker()

        # Determine stage_graph and stage_actions from profile, falling back to
        # TRACE sample defaults.
        stage_graph: Any | None = None
        stage_actions: dict | None = None
        if resolved_profile is not None:
            if resolved_profile.has_custom_graph:
                stage_graph = resolved_profile.stage_graph
                logger.info(
                    "_build_executor_impl: using profile %r stage_graph.",
                    resolved_profile.profile_id,
                )
            if resolved_profile.has_custom_actions:
                stage_actions = resolved_profile.stage_actions
                logger.info(
                    "_build_executor_impl: using profile %r stage_actions: %s.",
                    resolved_profile.profile_id,
                    list(stage_actions.keys()),
                )

        if resolved_profile is not None and (resolved_profile.has_custom_graph or resolved_profile.has_custom_actions):
            logger.info(
                "runtime mode=profile-runtime profile_id=%s has_custom_graph=%s has_custom_actions=%s",
                resolved_profile.profile_id,
                resolved_profile.has_custom_graph,
                resolved_profile.has_custom_actions,
            )
        else:
            logger.info("runtime mode=trace-sample-fallback (no resolved profile or profile has no custom topology)")

        # Validate required capabilities are available before building executor.
        if resolved_profile is not None and resolved_profile.required_capabilities:
            self._validate_required_capabilities(resolved_profile)

        executor = RunExecutor(
            contract=contract,
            kernel=self.build_kernel(),
            evolve_engine=self.build_evolve_engine(),
            harness_executor=self.build_harness(capability_invoker=invoker),
            human_gate_quality_threshold=self._config.gate_quality_threshold,
            event_emitter=EventEmitter(),
            raw_memory=RawMemoryStore(),
            compressor=self._build_compressor(),
            failure_collector=self.build_failure_collector(),
            watchdog=self.build_watchdog(),
            episode_builder=EpisodeBuilder(),
            episodic_store=self.build_episodic_store(),
            skill_recorder=self._build_skill_recorder(),
            skill_observer=self.build_skill_observer(),
            skill_version_mgr=self.build_skill_version_manager(),
            skill_loader=self.build_skill_loader(),
            state_store=RunStateStore(),
            policy_versions=PolicyVersionSet(),
            route_engine=self._build_route_engine(stage_actions=stage_actions),
            acceptance_policy=AcceptancePolicy(),
            short_term_store=self.build_short_term_store(),
            knowledge_query_fn=lambda q, **kw: km.query(q, **kw).wiki_pages,
            context_manager=self.build_context_manager(),
            budget_guard=self.build_budget_guard(),
            metrics_collector=self.build_metrics_collector(),
            llm_gateway=self.build_llm_gateway(),
            memory_lifecycle_manager=self.build_memory_lifecycle_manager(),
            retrieval_engine=self.build_retrieval_engine(),
            tier_router=self._tier_router,
            restart_policy_engine=self._build_restart_policy_engine(),
            reflection_orchestrator=self._build_reflection_orchestrator(),
            delegation_manager=self._build_delegation_manager(),
            stage_graph=stage_graph,  # None → RunExecutor defaults to TRACE graph
            compress_snip_threshold=self._config.compress_snip_threshold,
            compress_window_threshold=self._config.compress_window_threshold,
            compress_compress_threshold=self._config.compress_compress_threshold,
        )
        # Wire middleware orchestrator into the StageExecutor that RunExecutor
        # already created during __init__.  RunExecutor does not yet accept
        # middleware_orchestrator directly, so we inject it post-construction
        # via the StageExecutor's public instance attribute.
        try:
            mw = self._build_middleware_orchestrator()
            if mw is not None and hasattr(executor, "_stage_executor"):
                executor._stage_executor._middleware_orchestrator = mw
                logger.info(
                    "build_executor: MiddlewareOrchestrator wired into StageExecutor."
                )
                # Post-inject subsystem dependencies into middleware instances.
                # The orchestrator is built early (before all subsystems exist) so
                # dependencies are None at construction time.  We fill them here
                # after all subsystems have been built, avoiding circular deps.
                self._inject_middleware_dependencies(mw)
                # Inject profile evaluator into EvaluationMiddleware when profile
                # provides a custom evaluator factory.
                if resolved_profile is not None and resolved_profile.has_evaluator:
                    self._inject_evaluator(mw, resolved_profile)
        except Exception as exc:
            logger.warning(
                "build_executor: failed to wire MiddlewareOrchestrator, "
                "middleware path will be inactive: %s",
                exc,
            )
        # Wire SkillEvolver into RunLifecycle for automatic evolve_cycle() triggering.
        try:
            se = self.build_skill_evolver()
            if se is not None and hasattr(executor, "_lifecycle"):
                executor._lifecycle.skill_evolver = se
                executor._lifecycle._skill_evolve_interval = getattr(
                    self._config, "skill_evolve_interval", 10
                )
                logger.info("build_executor: SkillEvolver wired into RunLifecycle.")
        except Exception as exc:
            logger.warning(
                "build_executor: failed to wire SkillEvolver, "
                "auto evolve_cycle will be inactive: %s",
                exc,
            )
        # Wire JsonFileTraceExporter when trace_export_dir is configured.
        try:
            export_dir = getattr(self._config, "trace_export_dir", "")
            if export_dir and hasattr(executor, "_telemetry"):
                from hi_agent.observability.tracing import (  # noqa: PLC0415
                    JsonFileTraceExporter,
                    Tracer,
                )
                executor._telemetry.tracer = Tracer(
                    exporters=[JsonFileTraceExporter(export_dir)]
                )
                logger.info(
                    "build_executor: JsonFileTraceExporter wired (dir=%r).", export_dir
                )
        except Exception as exc:
            logger.warning(
                "build_executor: failed to wire JsonFileTraceExporter: %s", exc
            )
        return executor

    def _inject_evaluator(self, orchestrator: Any, resolved_profile: Any) -> None:
        """Inject profile evaluator into EvaluationMiddleware within the orchestrator."""
        try:
            from hi_agent.evaluation.runtime import EvaluatorRuntime  # noqa: PLC0415

            runtime = EvaluatorRuntime.from_resolved_profile(resolved_profile)
            middlewares: dict[str, Any] = getattr(orchestrator, "_middlewares", {})
            injected = False
            for mw in middlewares.values():
                if hasattr(mw, "_evaluator"):
                    mw._evaluator = runtime.evaluator
                    injected = True
            if injected:
                logger.info(
                    "_inject_evaluator: evaluator from profile %r injected into "
                    "EvaluationMiddleware.",
                    resolved_profile.profile_id,
                )
        except Exception as exc:
            logger.warning("_inject_evaluator: failed: %s", exc)

    def build_executor(
        self,
        contract: TaskContract,
        config_patch: dict | None = None,
    ) -> RunExecutor:
        """Build a RunExecutor.

        Resolves ``contract.profile_id`` against the platform ProfileRegistry
        and injects profile-derived stage_graph, stage_actions, and evaluator
        into the executor.  If config_patch provided, creates isolated per-run
        config.
        """
        resolved_profile = self._resolve_profile(getattr(contract, "profile_id", None))
        if config_patch:
            # Merge profile config_overrides into config_patch so profile
            # settings are respected even when the caller also passes a patch.
            if resolved_profile is not None and resolved_profile.config_overrides:
                merged = {**resolved_profile.config_overrides, **config_patch}
            else:
                merged = config_patch
            run_cfg = self._resolve_with_patch(merged)
            derived = SystemBuilder(
                config=run_cfg,
                profile_registry=self.build_profile_registry(),
                capability_registry=self.build_capability_registry(),
                artifact_registry=self.build_artifact_registry(),
            )
            # Inherit cached subsystem singletons so derived builders share
            # the same SkillLoader, MCPRegistry, MCPTransport, PluginLoader, and
            # EvidenceStore instances as the parent — avoids stale subsystems for
            # patched runs and prevents opening duplicate SQLite connections.
            derived._skill_loader = self._skill_loader
            derived._mcp_registry = self._mcp_registry
            derived._mcp_transport = self._mcp_transport
            derived._plugin_loader = self._plugin_loader
            derived._evidence_store = self._evidence_store
            return derived._build_executor_impl(contract, resolved_profile=resolved_profile)
        elif resolved_profile is not None and resolved_profile.config_overrides:
            run_cfg = self._resolve_with_patch(resolved_profile.config_overrides)
            derived = SystemBuilder(
                config=run_cfg,
                profile_registry=self.build_profile_registry(),
                capability_registry=self.build_capability_registry(),
                artifact_registry=self.build_artifact_registry(),
            )
            # Inherit cached subsystem singletons — same reasoning as above.
            derived._skill_loader = self._skill_loader
            derived._mcp_registry = self._mcp_registry
            derived._mcp_transport = self._mcp_transport
            derived._plugin_loader = self._plugin_loader
            derived._evidence_store = self._evidence_store
            return derived._build_executor_impl(contract, resolved_profile=resolved_profile)
        return self._build_executor_impl(contract, resolved_profile=resolved_profile)

    def build_executor_from_checkpoint(
        self, checkpoint_path: str
    ) -> Callable[[], str]:
        """Build a callable that resumes execution from a checkpoint.

        Args:
            checkpoint_path: Path to the checkpoint JSON file.

        Returns:
            A zero-argument callable that drives the resumed run to
            completion and returns the outcome string.
        """
        kernel = self.build_kernel()
        km = self.build_knowledge_manager()

        def resume() -> str:
            return RunExecutor.resume_from_checkpoint(
                checkpoint_path,
                kernel,
                evolve_engine=self.build_evolve_engine(),
                harness_executor=self.build_harness(),
                human_gate_quality_threshold=self._config.gate_quality_threshold,
                event_emitter=EventEmitter(),
                raw_memory=RawMemoryStore(),
                compressor=self._build_compressor(),
                failure_collector=self.build_failure_collector(),
                watchdog=self.build_watchdog(),
                episode_builder=EpisodeBuilder(),
                episodic_store=self.build_episodic_store(),
                skill_recorder=self._build_skill_recorder(),
                skill_observer=self.build_skill_observer(),
                skill_version_mgr=self.build_skill_version_manager(),
                skill_loader=self.build_skill_loader(),
                state_store=RunStateStore(),
                policy_versions=PolicyVersionSet(),
                route_engine=self._build_route_engine(),
                acceptance_policy=AcceptancePolicy(),
                short_term_store=self.build_short_term_store(),
                knowledge_query_fn=lambda q, **kw: km.query(q, **kw).wiki_pages,
                llm_gateway=self.build_llm_gateway(),
            )

        return resume

    def build_orchestrator(self) -> TaskOrchestrator:
        """Build a fully-wired TaskOrchestrator."""
        kernel = self.build_kernel()
        return TaskOrchestrator(kernel=kernel)

    def build_server(self) -> "Any":
        """Build API server with all subsystems connected."""
        from hi_agent.server.app import AgentServer  # noqa: PLC0415
        from hi_agent.server.run_manager import RunManager  # noqa: PLC0415

        server = AgentServer(
            host=self._config.server_host,
            port=self._config.server_port,
        )
        server.run_manager = RunManager(
            max_concurrent=self._config.server_max_concurrent_runs,
        )
        server.memory_manager = self.build_memory_lifecycle_manager()
        server.knowledge_manager = self.build_knowledge_manager()
        server.skill_evolver = self.build_skill_evolver()
        server.skill_loader = self.build_skill_loader()
        metrics = self.build_metrics_collector()
        server.metrics_collector = metrics
        server.run_context_manager = self._build_run_context_manager()

        # Wire SLOMonitor so lifespan.start()/stop() activates continuous
        # SLO evaluation rather than leaving it as a point-in-time snapshot.
        try:
            from hi_agent.management.slo import SLOMonitor  # noqa: PLC0415
            server.slo_monitor = SLOMonitor(metrics)
        except Exception:
            logger.warning("SLOMonitor initialization failed; SLO monitoring disabled.")

        return server

    def readiness(self) -> dict[str, Any]:
        """Return a live readiness snapshot of all platform subsystems.

        This method probes each subsystem and returns a structured dict that
        downstream integrators can use to verify platform state without reading
        source code.  It never raises — failures are captured as status entries.

        Returns a dict matching the platform manifest contract::

            {
              "ready": bool,
              "health": "ok" | "degraded",
              "execution_mode": str,
              "models": [...],
              "skills": [...],
              "mcp_servers": [...],
              "plugins": [...],
              "capabilities": [...],
              "subsystems": {...}
            }
        """
        result: dict[str, Any] = {
            "ready": False,
            "health": "ok",
            "execution_mode": "unknown",
            "models": [],
            "skills": [],
            "mcp_servers": [],
            "plugins": [],
            "capabilities": [],
            "subsystems": {},
        }
        issues: list[str] = []

        # --- kernel ---
        try:
            kernel = self.build_kernel()
            base_url = getattr(self._config, "kernel_base_url", "local") or "local"
            mode = "http" if base_url.lower() not in ("", "local") else "local"
            result["execution_mode"] = mode
            result["subsystems"]["kernel"] = {"status": "ok", "mode": mode}
        except Exception as exc:
            result["subsystems"]["kernel"] = {"status": "error", "error": str(exc)}
            result["health"] = "degraded"
            issues.append(f"kernel: {exc}")

        # --- LLM / models ---
        try:
            gateway = self.build_llm_gateway()
            if gateway is None:
                result["subsystems"]["llm"] = {"status": "not_configured"}
                result["models"] = []
            else:
                # Best-effort: list models from registry if tier router available
                model_names: list[str] = []
                if self._tier_router is not None:
                    try:
                        registry = getattr(self._tier_router, "_registry", None)
                        if registry is not None:
                            model_names = [
                                m if isinstance(m, str) else getattr(m, "name", str(m))
                                for m in registry.list_models()
                            ]
                    except Exception:
                        pass
                result["models"] = [{"name": n, "status": "configured"} for n in model_names]
                result["subsystems"]["llm"] = {"status": "ok", "models": len(model_names)}
        except Exception as exc:
            result["subsystems"]["llm"] = {"status": "error", "error": str(exc)}
            result["health"] = "degraded"
            issues.append(f"llm: {exc}")

        # --- capabilities ---
        try:
            invoker = self.build_invoker()
            # CapabilityInvoker exposes registry as public `registry` attribute.
            registry = getattr(invoker, "registry", None) or getattr(invoker, "_registry", None)
            cap_names: list[str] = []
            if registry is not None:
                cap_names = registry.list_names()
            result["capabilities"] = cap_names
            result["subsystems"]["capabilities"] = {"status": "ok", "count": len(cap_names)}
        except Exception as exc:
            result["subsystems"]["capabilities"] = {"status": "error", "error": str(exc)}
            result["health"] = "degraded"
            issues.append(f"capabilities: {exc}")

        # --- skills ---
        try:
            loader = self.build_skill_loader()
            # discover() triggers loading and returns the count (int), not a list.
            # Use list_skills() to get the actual SkillDefinition objects.
            skill_count = 0
            skill_list: list[Any] = []
            try:
                if hasattr(loader, "discover"):
                    skill_count = loader.discover()
                if hasattr(loader, "list_skills"):
                    skill_list = loader.list_skills()
                elif isinstance(skill_count, int):
                    skill_count = skill_count  # just the count, no list available
            except Exception:
                pass
            result["skills"] = [
                {
                    "name": getattr(s, "name", str(s)),
                    "source": getattr(s, "source", "unknown"),
                    "status": "loaded",
                }
                for s in skill_list
            ]
            result["subsystems"]["skills"] = {"status": "ok", "discovered": len(result["skills"])}
        except Exception as exc:
            result["subsystems"]["skills"] = {"status": "error", "error": str(exc)}
            issues.append(f"skills: {exc}")

        # --- MCP: use cached singleton so readiness reflects same state as runs ---
        try:
            from hi_agent.mcp.registry import MCPRegistry  # noqa: PLC0415
            if self._mcp_registry is None:
                self._mcp_registry = MCPRegistry()
            servers = self._mcp_registry.list_servers()
            # Annotate each server with transport availability so integrators know
            # whether tools are actually invokable vs just registered.
            for srv in servers:
                srv_status = srv.get("status", "registered")
                if srv_status == "healthy":
                    srv["availability"] = "available"
                elif srv_status in ("registered",):
                    srv["availability"] = "registered_but_no_transport"
                else:
                    srv["availability"] = srv_status
            result["mcp_servers"] = servers
            connected = sum(1 for s in servers if s.get("status") == "healthy")
            result["subsystems"]["mcp"] = {
                "status": "ok",
                "servers": len(servers),
                "connected": connected,
                "registered_only": len(servers) - connected,
                # Honest transport status for integrators.
                "transport_status": "not_wired",
                "capability_mode": "infrastructure_only",
                "note": (
                    "External MCP transport (stdio/SSE/HTTP) not yet implemented. "
                    "Platform tools are available via /mcp/tools/list as MCP-compatible "
                    "endpoints. External server registration and forwarding are deferred."
                ),
            }
        except ImportError:
            result["mcp_servers"] = []
            result["subsystems"]["mcp"] = {"status": "not_configured"}
        except Exception as exc:
            result["subsystems"]["mcp"] = {"status": "error", "error": str(exc)}

        # --- plugins: use cached singleton so readiness reflects same state as runs ---
        try:
            from hi_agent.plugin.loader import PluginLoader  # noqa: PLC0415
            if self._plugin_loader is None:
                self._plugin_loader = PluginLoader()
                # load_all() triggers actual discovery from plugin directories.
                # Without this, list_loaded() always returns [] on a fresh loader.
                self._plugin_loader.load_all()
            loaded = self._plugin_loader.list_loaded()
            result["plugins"] = loaded
            result["subsystems"]["plugins"] = {"status": "ok", "count": len(loaded)}
        except ImportError:
            result["plugins"] = []
            result["subsystems"]["plugins"] = {"status": "not_configured"}
        except Exception as exc:
            result["subsystems"]["plugins"] = {"status": "error", "error": str(exc)}

        # --- readiness decision ---
        kernel_ok = result["subsystems"].get("kernel", {}).get("status") == "ok"
        cap_ok = result["subsystems"].get("capabilities", {}).get("status") == "ok"
        # LLM error means prod mode requires credentials not present.
        # "not_configured" (dev fallback) is acceptable; "error" (missing prod creds) blocks.
        llm_status = result["subsystems"].get("llm", {}).get("status", "not_configured")
        llm_ok = llm_status != "error"
        result["ready"] = kernel_ok and cap_ok and llm_ok
        if not llm_ok:
            result["health"] = "degraded"
            issues.append("llm: credentials required for prod mode")
        if issues:
            logger.warning("readiness: %d issue(s): %s", len(issues), "; ".join(issues))

        # --- prerequisites transparency ---
        # Emit explicit prerequisites so integrators know exactly what is needed
        # when ready=false, without having to read source code.
        import os as _os
        env_mode = _os.environ.get("HI_AGENT_ENV", "dev").lower()
        result["runtime_mode"] = env_mode
        if env_mode == "prod":
            result["prerequisites"] = {
                "required_for_prod_mode": [
                    "OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable",
                    "kernel_base_url set to a real agent-kernel HTTP endpoint",
                ],
                "hint": (
                    "Run with HI_AGENT_ENV=dev (or use `serve` default) for "
                    "heuristic fallback without external dependencies."
                ),
            }
        else:
            result["prerequisites"] = {
                "mode": "dev — heuristic fallback active, no external dependencies required",
                "hint": "Use HI_AGENT_ENV=prod or `serve --prod` to require real credentials.",
            }

        return result
