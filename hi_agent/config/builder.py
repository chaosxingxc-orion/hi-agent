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
from hi_agent.server.app import AgentServer
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.server.run_manager import RunManager
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import SkillRegistry
from hi_agent.observability.collector import MetricsCollector
from hi_agent.state import RunStateStore


class SystemBuilder:
    """Factory that creates all TRACE subsystems from a single TraceConfig.

    This is the main assembly point -- creates properly configured
    instances of all subsystems and wires them together.
    """

    def __init__(
        self,
        config: TraceConfig | None = None,
        config_stack: Any | None = None,
    ) -> None:
        """Initialize SystemBuilder."""
        self._config = config if config is not None else TraceConfig()
        self._stack = config_stack
        # Cache built singletons so repeated calls return the same instance.
        self._kernel: RuntimeAdapter | None = None
        self._llm_gateway: LLMGateway | None = None
        self._metrics_collector: MetricsCollector | None = None
        self._tier_router: Any | None = None  # cached alongside _llm_gateway
        self._run_context_manager: Any | None = None
        self._middleware_orchestrator: Any | None = None
        self._llm_budget_tracker: Any | None = None

    # ------------------------------------------------------------------
    # Individual builders
    # ------------------------------------------------------------------

    def _build_run_context_manager(self) -> Any:
        """Build or return the shared RunContextManager singleton."""
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
            from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine

            engine = RestartPolicyEngine(
                get_attempts=lambda task_id: [],
                get_policy=lambda task_id: None,
                update_state=lambda task_id, state: None,
                record_attempt=lambda attempt: None,
            )
            logger.info("_build_restart_policy_engine: RestartPolicyEngine created.")
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
                if gateway is None:
                    return "reflect: no LLM gateway available"
                try:
                    from hi_agent.llm.protocol import LLMRequest
                    recovery_context = kwargs.get("recovery_context", {})
                    run_id = kwargs.get("run_id", "unknown")
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
                    return "reflect: inference failed"

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
        if self._kernel is None:
            base_url = self._config.kernel_base_url
            if base_url and base_url.lower() not in ("local", "mock"):
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

        logger.warning(
            "build_llm_gateway: no API key found in environment "
            "(checked %s). LLM features will use heuristic fallback. "
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

    def build_harness(self) -> HarnessExecutor:
        """Build HarnessExecutor with config-driven governance."""
        governance = GovernanceEngine()
        if self._config.evidence_store_backend == "sqlite":
            evidence_store: EvidenceStore | SqliteEvidenceStore = (
                SqliteEvidenceStore(db_path=self._config.evidence_store_path)
            )
        else:
            logger.warning(
                "build_harness: evidence_store_backend=%r — using in-memory store. "
                "Evidence will not persist across restarts. "
                "Set evidence_store_backend='sqlite' for production.",
                self._config.evidence_store_backend,
            )
            evidence_store = EvidenceStore()
        return HarnessExecutor(
            governance=governance,
            evidence_store=evidence_store,
        )

    def build_skill_registry(self) -> SkillRegistry:
        """Build SkillRegistry using configured storage directory."""
        return SkillRegistry(storage_dir=self._config.skill_storage_dir)

    def build_skill_loader(self) -> Any:
        """Build SkillLoader for multi-source skill discovery."""
        from hi_agent.skill.loader import SkillLoader

        dirs = [self._config.skill_storage_dir]
        return SkillLoader(
            search_dirs=dirs,
            max_skills_in_prompt=self._config.skill_loader_max_skills_in_prompt,
            max_prompt_tokens=self._config.skill_loader_max_prompt_tokens,
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
        except Exception:
            pass  # no prior state on first run
        return mgr

    def build_skill_evolver(self) -> Any:
        """Build SkillEvolver for observation-driven skill optimization."""
        from hi_agent.evolve.champion_challenger import ChampionChallenger
        from hi_agent.skill.evolver import SkillEvolver

        observer = self.build_skill_observer()
        version_mgr = self.build_skill_version_manager()
        gateway = self.build_llm_gateway()
        return SkillEvolver.from_config(
            cfg=self._config,
            llm_gateway=gateway,
            observer=observer,
            version_manager=version_mgr,
        )

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
        except Exception:
            pass  # no prior state on first run
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
        except Exception:
            pass  # no prior state on first run
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
        )

    def _build_route_engine(self) -> HybridRouteEngine:
        """Create HybridRouteEngine with LLM gateway + SkillMatcher if available."""
        registry = self.build_skill_registry()
        gateway = self.build_llm_gateway()
        matcher = SkillMatcher(registry=registry) if registry else None
        return HybridRouteEngine(
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
                        async_llm = _HTTPGateway(
                            base_url=base_url,
                            api_key=_os.environ[env_var],
                            default_model=default_model,
                            timeout=float(
                                getattr(self._config, "llm_timeout_seconds", 120)
                            ),
                        )
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

    def _build_executor_impl(self, contract: TaskContract) -> RunExecutor:
        """Build a fully-wired RunExecutor for a given task contract."""
        km = self.build_knowledge_manager()
        executor = RunExecutor(
            contract=contract,
            kernel=self.build_kernel(),
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
        return executor

    def build_executor(
        self,
        contract: TaskContract,
        config_patch: dict | None = None,
    ) -> RunExecutor:
        """Build a RunExecutor. If config_patch provided, creates isolated per-run config."""
        if config_patch:
            run_cfg = self._resolve_with_patch(config_patch)
            return SystemBuilder(config=run_cfg)._build_executor_impl(contract)
        return self._build_executor_impl(contract)

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

    def build_server(self) -> AgentServer:
        """Build API server with all subsystems connected."""
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
        server.metrics_collector = self.build_metrics_collector()
        server.run_context_manager = self._build_run_context_manager()
        return server
