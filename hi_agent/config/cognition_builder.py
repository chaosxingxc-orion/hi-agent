"""CognitionBuilder: LLM gateway, budget tracker, and evolve engine (HI-W10-002).

Extracted from SystemBuilder to reduce builder.py god-object footprint.
Holds all LLM-provider selection, failover, caching, and evolve-cycle logic.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.evolve.engine import EvolveEngine
    from hi_agent.llm.protocol import LLMGateway

_logger = logging.getLogger(__name__)


class CognitionBuilder:
    """Builds LLM gateway, budget tracker, and evolve engine subsystems.

    Receives *config* and a shared *singleton_lock* (re-entrant) so that
    repeated calls to :meth:`build_llm_gateway` return the same instance
    even under concurrent access.  Callers supply a *skill_version_mgr_fn*
    callback to resolve the SkillVersionManager without creating a circular
    import between CognitionBuilder and SystemBuilder.
    """

    def __init__(
        self,
        config: "TraceConfig",
        singleton_lock: Any,
        *,
        skill_version_mgr_fn: Any | None = None,
    ) -> None:
        self._config = config
        self._lock = singleton_lock
        self._skill_version_mgr_fn = skill_version_mgr_fn
        # Cached singletons
        self._llm_gateway: "LLMGateway | None" = None
        self._tier_router: Any | None = None
        self._llm_budget_tracker: Any | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cache_injector(self) -> Any | None:
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
            _logger.warning("Failed to build PromptCacheInjector, caching disabled: %s", exc)
            return None

    def _build_failover_chain(self, base_url: str, default_model: str) -> Any | None:
        """Build FailoverChain from env credential pool if failover is enabled."""
        try:
            if not getattr(self._config, "llm_failover_enabled", True):
                return None
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
                _logger.warning(
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
                    max_retries=0,
                    cache_injector=cache_injector,
                )

            policy = RetryPolicy(
                max_retries=getattr(self._config, "llm_failover_max_retries", 3),
                base_delay_ms=getattr(self._config, "llm_failover_base_delay_ms", 500),
                max_delay_ms=getattr(self._config, "llm_failover_max_delay_ms", 30_000),
            )
            chain = FailoverChain(gateway_factory=_gateway_factory, pool=pool, policy=policy)
            _logger.info(
                "_build_failover_chain: FailoverChain created (max_retries=%d, pool_size=%d)",
                policy.max_retries,
                len(pool),
            )
            return chain
        except ValueError as exc:
            _logger.info(
                "_build_failover_chain: credential pool unavailable (%s), failover disabled.", exc
            )
            return None
        except Exception as exc:
            _logger.warning("Failed to build FailoverChain, failover disabled: %s", exc)
            return None

    def _build_llm_budget_tracker(self) -> Any | None:
        """Build LLMBudgetTracker with config-driven limits."""
        try:
            from hi_agent.llm.budget_tracker import LLMBudgetTracker
            max_calls = getattr(self._config, "llm_budget_max_calls", 100)
            max_tokens = getattr(self._config, "llm_budget_max_tokens", 500_000)
            tracker = LLMBudgetTracker(max_calls=max_calls, max_tokens=max_tokens)
            _logger.info(
                "_build_llm_budget_tracker: LLMBudgetTracker created "
                "(max_calls=%d, max_tokens=%d).",
                max_calls,
                max_tokens,
            )
            return tracker
        except Exception as exc:
            _logger.warning(
                "_build_llm_budget_tracker: failed to create LLMBudgetTracker: %s", exc
            )
            return None

    def _wire_cost_optimizer(
        self,
        tier_router: Any,
        run_history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Apply cost optimization hints to tier_router based on run history."""
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
                _logger.info(
                    "Cost optimizer applied %d overrides at startup: %s",
                    len(overrides),
                    overrides,
                )
        except Exception as exc:
            _logger.warning("Cost optimizer wiring failed: %s", exc)

    # ------------------------------------------------------------------
    # Public builders
    # ------------------------------------------------------------------

    def build_llm_gateway(self) -> "LLMGateway | None":
        """Build LLM gateway — auto-activates if API key found in env.

        Returns ``None`` when no key is configured; downstream subsystems
        fall back to heuristic behaviour.
        """
        from hi_agent.llm.anthropic_gateway import AnthropicLLMGateway
        from hi_agent.llm.http_gateway import HttpLLMGateway
        from hi_agent.llm.registry import ModelRegistry
        from hi_agent.llm.tier_router import TierAwareLLMGateway, TierRouter

        with self._lock:
            if self._llm_gateway is not None:
                return self._llm_gateway

            _provider_params = {
                "anthropic": (
                    self._config.anthropic_api_key_env,
                    self._config.anthropic_base_url,
                    self._config.anthropic_default_model,
                ),
                "openai": (
                    self._config.openai_api_key_env,
                    self._config.openai_base_url,
                    self._config.openai_default_model,
                ),
            }
            default_provider = getattr(self._config, "llm_default_provider", "anthropic")
            provider_order = (
                ["anthropic", "openai"]
                if default_provider == "anthropic"
                else ["openai", "anthropic"]
            )
            for provider in provider_order:
                env_var, base_url, default_model = _provider_params[provider]
                if os.environ.get(env_var):
                    cache_injector = self._build_cache_injector()
                    failover_chain = self._build_failover_chain(base_url, default_model)
                    if self._llm_budget_tracker is None:
                        self._llm_budget_tracker = self._build_llm_budget_tracker()
                    if provider == "anthropic":
                        from hi_agent.llm.protocol import LLMGateway  # noqa: F401
                        raw_gateway: "LLMGateway" = AnthropicLLMGateway(
                            api_key_env=env_var,
                            default_model=default_model,
                            timeout_seconds=self._config.llm_timeout_seconds,
                            base_url=base_url,
                        )
                    else:
                        # API key is confirmed present at this point.
                        # Use "local-real" so the gateway uses full timeouts/retries;
                        # "dev-smoke" is reserved for credential-absent scenarios.
                        from hi_agent.server.runtime_mode_resolver import (
                            resolve_runtime_mode as _rrm,
                        )
                        _env = os.environ.get("HI_AGENT_ENV", "")
                        _rt_mode = _rrm(
                            _env,
                            {
                                "llm_mode": getattr(self._config, "llm_mode", None) or "real",
                                "kernel_mode": getattr(self._config, "kernel_mode", None) or "http",
                            },
                        )
                        _compat_sync = getattr(self._config, "compat_sync_llm", False)
                        raw_gateway = HttpLLMGateway(
                            base_url=base_url,
                            api_key_env=env_var,
                            default_model=default_model,
                            timeout_seconds=self._config.llm_timeout_seconds,
                            failover_chain=failover_chain,
                            cache_injector=cache_injector,
                            budget_tracker=self._llm_budget_tracker,
                            runtime_mode="" if _compat_sync else _rt_mode,
                        )
                    registry = ModelRegistry()
                    registry.register_defaults()
                    tier_router = TierRouter(registry)
                    self._tier_router = tier_router
                    startup_history: list[dict[str, Any]] | None = getattr(
                        self._config, "startup_cost_history", None
                    )
                    self._wire_cost_optimizer(tier_router, startup_history)
                    self._llm_gateway = TierAwareLLMGateway(raw_gateway, tier_router, registry)  # type: ignore[assignment]
                    return self._llm_gateway

        # Fallback: try loading from llm_config.json
        try:
            from hi_agent.config.json_config_loader import build_gateway_from_config
            gw = build_gateway_from_config()
            if gw is not None:
                with self._lock:
                    self._llm_gateway = gw  # type: ignore[assignment]
                _logger.info(
                    "build_llm_gateway: activated gateway from llm_config.json "
                    "(provider=%s)",
                    getattr(getattr(gw, "_inner", None), "__class__", type(gw)).__name__,
                )
                return self._llm_gateway
        except Exception as _cfg_exc:
            _logger.debug("build_llm_gateway: config-file fallback failed: %s", _cfg_exc)

        is_prod = os.environ.get("HI_AGENT_ENV", "dev").lower() == "prod"
        if is_prod:
            raise RuntimeError(
                "Production mode requires real LLM credentials. "
                "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or fill in config/llm_config.json."
            )
        _logger.warning(
            "build_llm_gateway: no API key found in environment "
            "(checked %s) and no active provider in llm_config.json. "
            "LLM features will use heuristic fallback.",
            ", ".join([self._config.openai_api_key_env, self._config.anthropic_api_key_env]),
        )
        return None

    def _build_regression_detector(self) -> Any:
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
        except Exception as exc:
            _logger.debug("RegressionDetector.load skipped: %s", exc)
        return detector

    def build_evolve_engine(self) -> "EvolveEngine":
        """Build EvolveEngine with config-driven parameters."""
        from hi_agent.evolve.champion_challenger import ChampionChallenger
        from hi_agent.evolve.engine import EvolveEngine
        from hi_agent.evolve.skill_extractor import SkillExtractor

        gateway = self.build_llm_gateway()
        skill_version_mgr = (
            self._skill_version_mgr_fn() if self._skill_version_mgr_fn is not None else None
        )
        return EvolveEngine(
            llm_gateway=gateway,
            skill_extractor=SkillExtractor(
                min_confidence=self._config.evolve_min_confidence,
                gateway=gateway,
            ),
            regression_detector=self._build_regression_detector(),
            champion_challenger=ChampionChallenger(),
            version_manager=skill_version_mgr,
        )

    def build_reflection_orchestrator(self) -> Any | None:
        """Build ReflectionOrchestrator wired to the LLM gateway if available."""
        try:
            from hi_agent.task_mgmt.reflection import ReflectionOrchestrator
            from hi_agent.task_mgmt.reflection_bridge import ReflectionBridge

            gateway = self.build_llm_gateway()

            async def _inference_fn(**kwargs: Any) -> str:
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
                    req = LLMRequest(messages=[{"role": "user", "content": prompt}], max_tokens=256)
                    resp = gateway.complete(req)
                    return resp.content
                except Exception as exc:
                    _logger.warning("_reflection_orchestrator inference_fn error: %s", exc)
                    return _json.dumps({
                        "action": "retry_with_default",
                        "reason": f"inference failed: {exc}",
                        "run_id": run_id,
                    })

            bridge = ReflectionBridge()
            orchestrator = ReflectionOrchestrator(bridge=bridge, inference_fn=_inference_fn)
            _logger.info("build_reflection_orchestrator: ReflectionOrchestrator created.")
            return orchestrator
        except Exception as exc:
            _logger.warning(
                "build_reflection_orchestrator: failed to create ReflectionOrchestrator: %s", exc
            )
            return None
