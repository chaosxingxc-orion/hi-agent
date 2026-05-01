"""Tier-based model routing: task complexity -> model tier -> specific model.

Three tiers: strong, medium, light.
Each middleware/stage/purpose maps to a default tier.
Task complexity can override: simple->light, moderate->medium, complex->strong.
Cost budget can force downgrade: strong->medium->light.
Quality failure can force upgrade: light->medium->strong.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass

from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel

_logger = logging.getLogger(__name__)

# Tier ordering for upgrade/downgrade logic
_TIER_ORDER = [ModelTier.LIGHT, ModelTier.MEDIUM, ModelTier.STRONG]


def _tier_index(tier: str) -> int:
    """Return numeric index for a tier (0=light, 1=medium, 2=strong)."""
    try:
        return _TIER_ORDER.index(tier)
    except ValueError:
        return 1  # default to medium


@dataclass
class TierMapping:
    """Maps a purpose to a default model tier."""

    purpose: str  # middleware name, stage_id, or custom label
    default_tier: str  # strong/medium/light
    allow_upgrade: bool = True  # can upgrade if quality is low
    allow_downgrade: bool = True  # can downgrade if budget is tight


class TierRouter:
    """Routes requests to models based on tier + complexity + budget."""

    def __init__(self, registry: ModelRegistry) -> None:
        """Initialize TierRouter."""
        self._registry = registry
        self._tier_map: dict[str, TierMapping] = {}
        self._complexity_overrides: dict[str, str] = {
            "simple": ModelTier.LIGHT,
            "moderate": ModelTier.MEDIUM,
            "complex": ModelTier.STRONG,
        }
        self._lock = threading.Lock()
        self._calibration_log: list = []
        self._setup_defaults()

    def _setup_defaults(self) -> None:
        """Default middleware -> tier mapping."""
        defaults = [
            TierMapping("perception", ModelTier.LIGHT),
            TierMapping("control", ModelTier.MEDIUM),
            TierMapping("execution", ModelTier.MEDIUM),
            TierMapping("evaluation", ModelTier.LIGHT),
            TierMapping("compression", ModelTier.LIGHT),
            TierMapping("routing", ModelTier.MEDIUM),
            TierMapping("skill_extraction", ModelTier.MEDIUM),
        ]
        for mapping in defaults:
            self._tier_map[mapping.purpose] = mapping

    def set_tier(
        self,
        purpose: str,
        tier: str,
        allow_upgrade: bool = True,
        allow_downgrade: bool = True,
    ) -> None:
        """Override the tier for a purpose."""
        with self._lock:
            self._tier_map[purpose] = TierMapping(
                purpose=purpose,
                default_tier=tier,
                allow_upgrade=allow_upgrade,
                allow_downgrade=allow_downgrade,
            )

    def _resolve_tier(
        self,
        purpose: str,
        complexity: str,
        budget_remaining_usd: float | None,
        skill_confidence: float | None = None,
    ) -> str:
        """Determine effective tier considering purpose, complexity, budget, skill confidence."""
        with self._lock:
            mapping = self._tier_map.get(purpose)
        base_tier = mapping.default_tier if mapping else ModelTier.MEDIUM
        allow_upgrade = mapping.allow_upgrade if mapping else True
        allow_downgrade = mapping.allow_downgrade if mapping else True

        # Complexity override: only "simple" and "complex" move the tier.
        # "moderate" is neutral and does not override the purpose mapping.
        if complexity != "moderate":
            complexity_tier = self._complexity_overrides.get(complexity)
            if complexity_tier is not None:
                ci = _tier_index(complexity_tier)
                bi = _tier_index(base_tier)
                if (ci > bi and allow_upgrade) or (ci < bi and allow_downgrade):
                    base_tier = complexity_tier

        # Budget pressure: if budget is low, try to downgrade
        if budget_remaining_usd is not None and allow_downgrade:
            if budget_remaining_usd < 0.10:
                base_tier = ModelTier.LIGHT
            elif budget_remaining_usd < 0.50:
                idx = _tier_index(base_tier)
                if idx > 0:
                    base_tier = _TIER_ORDER[idx - 1]

        # Skill confidence downgrade: if a proven high-confidence skill handles
        # this purpose, a cheaper model tier is sufficient (one step down).
        if skill_confidence is not None and skill_confidence >= 0.85 and allow_downgrade:
            idx = _tier_index(base_tier)
            if idx > 0:
                base_tier = _TIER_ORDER[idx - 1]

        return base_tier

    def select_model(
        self,
        purpose: str,
        complexity: str = "moderate",
        required_capabilities: list[str] | None = None,
        budget_remaining_usd: float | None = None,
        min_context_window: int = 0,
        skill_confidence: float | None = None,
        meta: dict | None = None,
    ) -> RegisteredModel:
        """Select the best model for a given request.

        Algorithm:
        1. Determine tier from purpose mapping
        2. Override tier based on complexity (simple->light, complex->strong)
        3. If budget_remaining is low, downgrade tier
        4. If skill_confidence >= 0.85, downgrade one additional tier
        5. Filter by required_capabilities and min_context_window
        6. From matching models, pick cheapest available
        7. If no match in target tier, try adjacent tier

        Raises:
            KeyError: If no suitable model can be found.
        """
        target_tier = self._resolve_tier(
            purpose, complexity, budget_remaining_usd, skill_confidence
        )
        model = self._find_in_tier(target_tier, required_capabilities, min_context_window)
        if model is not None:
            _logger.info(
                '{"event": "tier_routing", "tier": "%s", "model": "%s", "purpose": "%s"}',
                target_tier,
                model.model_id,
                purpose,
            )
            return model

        # Fallback: try adjacent tiers
        idx = _tier_index(target_tier)
        # Try one tier down, then one tier up
        for offset in [-1, 1, -2, 2]:
            adj = idx + offset
            if 0 <= adj < len(_TIER_ORDER):
                model = self._find_in_tier(
                    _TIER_ORDER[adj], required_capabilities, min_context_window
                )
                if model is not None:
                    _logger.info(
                        '{"event": "tier_routing", "tier": "%s", "model": "%s",'
                        ' "purpose": "%s", "fallback_from": "%s"}',
                        _TIER_ORDER[adj],
                        model.model_id,
                        purpose,
                        target_tier,
                    )
                    from hi_agent.observability.fallback import record_fallback
                    _adj = _TIER_ORDER[adj]
                    record_fallback(
                        "llm",
                        reason=f"tier_downgrade purpose={purpose} from={target_tier} to={_adj}",
                        run_id=(meta.get("run_id") if meta else None) or "unknown",
                    )
                    return model

        # Last resort: any available model
        available = self._registry.list_available()
        if available:
            best = min(
                available,
                key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
            )
            _logger.info(
                '{"event": "tier_routing", "tier": "%s", "model": "%s",'
                ' "purpose": "%s", "fallback_from": "%s"}',
                best.tier,
                best.model_id,
                purpose,
                target_tier,
            )
            from hi_agent.observability.fallback import record_fallback
            record_fallback(
                "llm",
                reason=f"tier_last_resort purpose={purpose} from={target_tier}",
                run_id=(meta.get("run_id") if meta else None) or "unknown",
            )
            return best

        raise KeyError(
            f"No suitable model found for purpose={purpose!r}, complexity={complexity!r}"
        )

    def _find_in_tier(
        self,
        tier: str,
        required_capabilities: list[str] | None,
        min_context_window: int,
    ) -> RegisteredModel | None:
        """Find cheapest available model in tier matching constraints."""
        candidates = [
            m
            for m in self._registry.list_by_tier(tier)
            if m.is_available and m.context_window >= min_context_window
        ]
        if required_capabilities:
            candidates = [
                m for m in candidates if all(cap in m.capabilities for cap in required_capabilities)
            ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
        )

    def select_with_fallback(
        self,
        purpose: str,
        complexity: str = "moderate",
        meta: dict | None = None,
        **kwargs: object,
    ) -> tuple[RegisteredModel, str]:
        """Select model with fallback chain. Returns (model, actual_tier).

        Fallback: target_tier -> one tier down -> one tier up -> any available.
        Supports skill_confidence kwarg: if >= 0.85, allows one additional tier downgrade.
        """
        target_tier = self._resolve_tier(
            purpose,
            complexity,
            kwargs.get("budget_remaining_usd"),  # type: ignore[arg-type]  expiry_wave: Wave 28
            kwargs.get("skill_confidence"),  # type: ignore[arg-type]
        )
        required_caps: list[str] | None = kwargs.get("required_capabilities")  # type: ignore[assignment]  expiry_wave: Wave 28
        min_ctx: int = kwargs.get("min_context_window", 0)  # type: ignore[assignment]

        # Try target tier
        model = self._find_in_tier(target_tier, required_caps, min_ctx)
        if model is not None:
            _logger.info(
                '{"event": "tier_routing", "tier": "%s", "model": "%s", "purpose": "%s"}',
                target_tier,
                model.model_id,
                purpose,
            )
            return model, target_tier

        # Try adjacent tiers
        idx = _tier_index(target_tier)
        for offset in [-1, 1, -2, 2]:
            adj = idx + offset
            if 0 <= adj < len(_TIER_ORDER):
                adj_tier = _TIER_ORDER[adj]
                model = self._find_in_tier(adj_tier, required_caps, min_ctx)
                if model is not None:
                    _logger.info(
                        '{"event": "tier_routing", "tier": "%s", "model": "%s",'
                        ' "purpose": "%s", "fallback_from": "%s"}',
                        adj_tier,
                        model.model_id,
                        purpose,
                        target_tier,
                    )
                    from hi_agent.observability.fallback import record_fallback
                    record_fallback(
                        "llm",
                        reason=(
                            f"tier_downgrade purpose={purpose}"
                            f" from={target_tier} to={adj_tier}"
                        ),
                        run_id=(meta.get("run_id") if meta else None) or "unknown",
                    )
                    return model, adj_tier

        # Any available
        available = self._registry.list_available()
        if available:
            best = min(
                available,
                key=lambda m: m.cost_input_per_mtok + m.cost_output_per_mtok,
            )
            _logger.info(
                '{"event": "tier_routing", "tier": "%s", "model": "%s",'
                ' "purpose": "%s", "fallback_from": "%s"}',
                best.tier,
                best.model_id,
                purpose,
                target_tier,
            )
            from hi_agent.observability.fallback import record_fallback
            record_fallback(
                "llm",
                reason=f"tier_last_resort purpose={purpose} from={target_tier}",
                run_id=(meta.get("run_id") if meta else None) or "unknown",
            )
            return best, best.tier

        raise KeyError(f"No models available for purpose={purpose!r}")

    def estimate_cost(
        self,
        purpose: str,
        complexity: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost for a request without actually selecting."""
        model = self.select_model(purpose, complexity)
        return model.estimated_cost(input_tokens, output_tokens)

    def get_tier_for_purpose(self, purpose: str) -> str:
        """Get the configured tier for a purpose."""
        with self._lock:
            mapping = self._tier_map.get(purpose)
        return mapping.default_tier if mapping else ModelTier.MEDIUM

    def apply_overrides(self, overrides: dict[str, str]) -> None:
        """Apply purpose->tier override mapping from cost optimizer.

        Each key is a purpose name (e.g. "gather", "retrieval"); value is
        the target tier string ("light", "medium", "strong").  Existing
        allow_upgrade/allow_downgrade flags are preserved.
        """
        with self._lock:
            for purpose, tier in overrides.items():
                existing = self._tier_map.get(purpose)
                allow_upgrade = existing.allow_upgrade if existing else True
                allow_downgrade = existing.allow_downgrade if existing else True
                self._tier_map[purpose] = TierMapping(
                    purpose=purpose,
                    default_tier=tier,
                    allow_upgrade=allow_upgrade,
                    allow_downgrade=allow_downgrade,
                )

    def apply_cost_overrides(self, overrides: dict[str, str]) -> None:
        """Apply cost optimization tier overrides dynamically.

        Convenience alias for :meth:`apply_overrides` that matches the
        method name expected by SystemBuilder._wire_cost_optimizer and
        runner.py post-run hooks.

        Args:
            overrides: mapping of purpose -> tier,
                e.g. ``{"gather": "light", "retrieval": "light"}``.
                Keys use the same purpose vocabulary as the rest of
                TierRouter (``"gather"``, ``"retrieval"``,
                ``"synthesis"``, ``"evaluation"``, etc.).
        """
        self.apply_overrides(overrides)

    def ingest_calibration_signal(self, signal: object) -> None:
        """Record a calibration signal for future TierRouter auto-tuning.

        Currently record-only: signals are stored but do not modify tier routing.
        Auto-calibration requires stable usage data; wave 10 deadline missed,
        retargeted Wave 12 (owner: CO).

        Args:
            signal: A CalibrationSignal instance from hi_agent.evolve.contracts.
        """
        self._calibration_log.append(signal)

    def list_mappings(self) -> list[TierMapping]:
        """List all purpose -> tier mappings."""
        with self._lock:
            return list(self._tier_map.values())


class TierAwareLLMGateway:
    """Wraps any LLMGateway to use TierRouter for model selection.

    Intercepts complete() calls, reads metadata["purpose"] to select
    the appropriate model tier, then delegates to the inner gateway.
    This implements P2 (cost continuously decreases) by ensuring that
    light/medium/strong tier settings stored in request metadata are
    actually honoured during model selection.
    """

    def __init__(self, inner: object, tier_router: TierRouter, registry: ModelRegistry) -> None:
        """Initialize TierAwareLLMGateway."""
        self._inner = inner
        self._tier_router = tier_router
        self._registry = registry

    def complete(self, request: object) -> object:
        """Route to appropriate model tier based on request purpose.

        If request.model == "default", reads metadata["purpose"],
        metadata["budget_remaining"] (0-1 fraction), and
        metadata["complexity"] to pick a model via TierRouter, then
        rewrites the request with the selected model_id before
        delegating to the inner gateway.
        """
        from hi_agent.llm.protocol import LLMRequest

        if getattr(request, "model", None) == "default":
            meta = getattr(request, "metadata", None) or {}
            purpose: str = meta.get("purpose", "routing")
            # budget_remaining is a 0-1 fraction; scale to rough USD so
            # that the TierRouter budget thresholds (0.10, 0.50) work
            # meaningfully: treat 1.0 fraction as $1.00.
            budget_fraction: float = float(meta.get("budget_remaining", 1.0))
            budget_usd: float = budget_fraction  # 1:1 mapping, fraction acts as proxy
            complexity: str = meta.get("complexity", "moderate")
            # skill_confidence: optional float from SkillObserver.get_metrics().success_rate.
            # If >= 0.85, the proven skill handles this well, so a cheaper tier suffices.
            raw_sc = meta.get("skill_confidence")
            skill_confidence: float | None = float(raw_sc) if raw_sc is not None else None
            try:
                result = self._tier_router.select_model(
                    purpose=purpose,
                    budget_remaining_usd=budget_usd,
                    complexity=complexity,
                    skill_confidence=skill_confidence,
                )
                request = LLMRequest(
                    messages=getattr(request, "messages", []),
                    model=result.model_id,
                    temperature=getattr(request, "temperature", 0.7),
                    max_tokens=getattr(request, "max_tokens", 4096),
                    stop_sequences=getattr(request, "stop_sequences", []),
                    metadata=meta,
                    thinking_budget=getattr(request, "thinking_budget", None),
                )
            except Exception as _tier_exc:
                _logger.warning(
                    "TierAwareLLMGateway: select_model failed (purpose=%s), "
                    "falling back to inner gateway with original request. Error: %s",
                    meta.get("purpose", "unknown"),
                    _tier_exc,
                )
                from hi_agent.observability.fallback import record_fallback
                record_fallback(
                    "llm",
                    reason=(
                        f"tier_exception purpose={meta.get('purpose', 'unknown')}"
                        f" error={type(_tier_exc).__name__}"
                    ),
                    run_id=meta.get("run_id") or "unknown",
                )

        return self._inner.complete(request)  # type: ignore[union-attr]  expiry_wave: Wave 28

    def stream(self, request: object) -> Iterator[object]:
        """Stream response chunks with tier-based model selection.

        Applies the same tier routing as :meth:`complete`, then delegates
        to ``inner.stream()``.  Falls back to accumulating ``complete()``
        and yielding a single chunk if the inner gateway has no ``stream``.
        """
        from hi_agent.llm.protocol import LLMRequest, LLMStreamChunk

        if getattr(request, "model", None) == "default":
            meta = getattr(request, "metadata", None) or {}
            purpose: str = meta.get("purpose", "routing")
            budget_usd: float = float(meta.get("budget_remaining", 1.0))
            complexity: str = meta.get("complexity", "moderate")
            raw_sc = meta.get("skill_confidence")
            skill_confidence: float | None = float(raw_sc) if raw_sc is not None else None
            try:
                result = self._tier_router.select_model(
                    purpose=purpose,
                    budget_remaining_usd=budget_usd,
                    complexity=complexity,
                    skill_confidence=skill_confidence,
                )
                request = LLMRequest(
                    messages=getattr(request, "messages", []),
                    model=result.model_id,
                    temperature=getattr(request, "temperature", 0.7),
                    max_tokens=getattr(request, "max_tokens", 4096),
                    stop_sequences=getattr(request, "stop_sequences", []),
                    metadata=meta,
                    thinking_budget=getattr(request, "thinking_budget", None),
                )
            except Exception as _tier_exc:
                _logger.warning("TierAwareLLMGateway.stream: select_model failed: %s", _tier_exc)
                from hi_agent.observability.fallback import record_fallback
                record_fallback(
                    "llm",
                    reason=(
                        f"tier_exception purpose={meta.get('purpose', 'unknown')}"
                        f" error={type(_tier_exc).__name__}"
                    ),
                    run_id=meta.get("run_id") or "unknown",
                )

        inner_stream = getattr(self._inner, "stream", None)
        if callable(inner_stream):
            yield from inner_stream(request)
        else:
            # Fallback: single-chunk yield from complete()
            resp = self._inner.complete(request)  # type: ignore[union-attr]  expiry_wave: Wave 28
            yield LLMStreamChunk(
                delta=getattr(resp, "content", ""),
                finish_reason=getattr(resp, "finish_reason", "stop"),
                usage=getattr(resp, "usage", None),
                model=getattr(resp, "model", ""),
            )

    async def acomplete(self, request: object) -> object:
        """Async variant: apply tier selection then await inner.complete().

        Enables TierAwareLLMGateway to satisfy the AsyncLLMGateway protocol
        so that async callers (e.g. DelegationManager) also benefit from
        tier routing.  The inner gateway must implement async ``complete()``.
        """
        from hi_agent.llm.protocol import LLMRequest

        if getattr(request, "model", None) == "default":
            meta = getattr(request, "metadata", None) or {}
            purpose: str = meta.get("purpose", "routing")
            budget_usd: float = float(meta.get("budget_remaining", 1.0))
            complexity: str = meta.get("complexity", "moderate")
            raw_sc = meta.get("skill_confidence")
            skill_confidence: float | None = float(raw_sc) if raw_sc is not None else None
            try:
                result = self._tier_router.select_model(
                    purpose=purpose,
                    budget_remaining_usd=budget_usd,
                    complexity=complexity,
                    skill_confidence=skill_confidence,
                )
                request = LLMRequest(
                    messages=getattr(request, "messages", []),
                    model=result.model_id,
                    temperature=getattr(request, "temperature", 0.7),
                    max_tokens=getattr(request, "max_tokens", 4096),
                    stop_sequences=getattr(request, "stop_sequences", []),
                    metadata=meta,
                    thinking_budget=getattr(request, "thinking_budget", None),
                )
            except Exception as _tier_exc:
                _logger.warning(
                    "TierAwareLLMGateway.acomplete: select_model failed (purpose=%s), "
                    "falling back with original request. Error: %s",
                    meta.get("purpose", "unknown"),
                    _tier_exc,
                )
                from hi_agent.observability.fallback import record_fallback
                record_fallback(
                    "llm",
                    reason=(
                        f"tier_exception purpose={meta.get('purpose', 'unknown')}"
                        f" error={type(_tier_exc).__name__}"
                    ),
                    run_id=meta.get("run_id") or "unknown",
                )

        return await self._inner.complete(request)  # type: ignore[union-attr]  expiry_wave: Wave 28

    def supports_model(self, model: str) -> bool:
        """Delegate to inner gateway."""
        return self._inner.supports_model(model)  # type: ignore[union-attr]  expiry_wave: Wave 28
