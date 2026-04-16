"""Load LLM configuration from config/llm_config.json into TraceConfig.

Two public functions:

- ``load_from_json_config``: returns (TraceConfig, SystemBuilder) with env vars
  injected from the JSON file; suitable for callers that rely on
  SystemBuilder.build_llm_gateway() later.

- ``build_gateway_from_config``: builds a fully-wired TierAwareLLMGateway
  directly from the active provider entry in the JSON file, supporting
  arbitrary providers beyond the default anthropic/openai pair.

Usage::

    # Option A — full builder path
    from hi_agent.config.json_config_loader import load_from_json_config
    cfg, builder = load_from_json_config()
    gateway = builder.build_llm_gateway()

    # Option B — direct gateway from any provider
    from hi_agent.config.json_config_loader import build_gateway_from_config
    gateway = build_gateway_from_config()
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.llm.protocol import LLMGateway

_logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "llm_config.json"


def load_from_json_config(
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
) -> tuple[TraceConfig, SystemBuilder]:
    """Read llm_config.json, inject API keys into env, return (TraceConfig, SystemBuilder).

    Injects ``ANTHROPIC_API_KEY`` and ``OPENAI_API_KEY`` from the config's
    ``providers.anthropic`` and ``providers.openai`` entries respectively.
    Other provider keys are injected as ``HI_AGENT_LLM_API_KEY_<PROVIDER>``.

    If the config file does not exist, returns a default TraceConfig and
    SystemBuilder without injecting any keys.

    Args:
        config_path: Path to the JSON config file. Defaults to
            ``config/llm_config.json`` relative to the repository root.

    Returns:
        A ``(TraceConfig, SystemBuilder)`` tuple ready for use.
    """
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    path = Path(config_path)
    if not path.exists():
        _logger.warning("json_config_loader: %s not found, using defaults", path)
        cfg = TraceConfig()
        return cfg, SystemBuilder(cfg)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    kwargs: dict = {}
    providers = data.get("providers", {})
    budget = data.get("budget", {})
    default_provider = data.get("default_provider", "anthropic")

    # --- Anthropic ---
    anthropic = providers.get("anthropic", {})
    if anthropic.get("api_key"):
        os.environ["ANTHROPIC_API_KEY"] = anthropic["api_key"]
        _logger.info("json_config_loader: ANTHROPIC_API_KEY loaded from config")
    if anthropic.get("base_url"):
        kwargs["anthropic_base_url"] = anthropic["base_url"]
    models_a = anthropic.get("models", {})
    if models_a.get("medium"):
        kwargs["anthropic_default_model"] = models_a["medium"]

    # --- OpenAI ---
    openai_cfg = providers.get("openai", {})
    if openai_cfg.get("api_key"):
        os.environ["OPENAI_API_KEY"] = openai_cfg["api_key"]
        _logger.info("json_config_loader: OPENAI_API_KEY loaded from config")
    if openai_cfg.get("base_url"):
        kwargs["openai_base_url"] = openai_cfg["base_url"]
    models_o = openai_cfg.get("models", {})
    if models_o.get("medium"):
        kwargs["openai_default_model"] = models_o["medium"]

    # --- Budget ---
    if budget.get("max_calls"):
        kwargs["llm_budget_max_calls"] = budget["max_calls"]
    if budget.get("max_tokens"):
        kwargs["llm_budget_max_tokens"] = budget["max_tokens"]
    if budget.get("max_output_tokens"):
        kwargs["llm_default_max_output_tokens"] = budget["max_output_tokens"]

    # --- Default provider ---
    kwargs["llm_default_provider"] = default_provider

    cfg = TraceConfig(**kwargs)
    builder = SystemBuilder(cfg)
    return cfg, builder


def build_gateway_from_config(
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
) -> LLMGateway | None:
    """Build a TierAwareLLMGateway directly from the active provider in llm_config.json.

    Reads the provider named by ``default_provider``, injects its ``api_key``
    into a unique env var, builds the appropriate gateway (AnthropicLLMGateway
    for ``api_format: "anthropic"``, HttpLLMGateway for ``api_format: "openai"``),
    registers all declared models into a ModelRegistry, and wraps the result in
    a TierAwareLLMGateway.

    This is the entry point for third-party providers that share an
    Anthropic-compatible endpoint (e.g. DashScope coding plan).

    Args:
        config_path: Path to the JSON config file.

    Returns:
        A configured :class:`~hi_agent.llm.tier_router.TierAwareLLMGateway`,
        or ``None`` if the active provider has no ``api_key``.
    """
    from hi_agent.llm.registry import ModelRegistry, ModelTier, RegisteredModel
    from hi_agent.llm.tier_router import TierAwareLLMGateway, TierRouter

    path = Path(config_path)
    if not path.exists():
        _logger.warning("build_gateway_from_config: %s not found", path)
        return None

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    default_provider = data.get("default_provider", "anthropic")
    providers = data.get("providers", {})
    provider_cfg = providers.get(default_provider, {})

    api_key = provider_cfg.get("api_key", "")
    if not api_key:
        _logger.warning(
            "build_gateway_from_config: provider %r has no api_key in config",
            default_provider,
        )
        return None

    base_url = provider_cfg.get("base_url", "")
    api_format = provider_cfg.get("api_format", "anthropic")
    models_cfg = provider_cfg.get("models", {})
    default_model = models_cfg.get("medium") or models_cfg.get("strong") or ""

    # --- Inject API key into a stable env var ---
    _ENV_VAR_MAP = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
    env_var = _ENV_VAR_MAP.get(default_provider) or f"HI_AGENT_LLM_API_KEY_{default_provider.upper()}"
    os.environ[env_var] = api_key
    _logger.info(
        "build_gateway_from_config: provider=%r format=%r key_env=%s",
        default_provider, api_format, env_var,
    )

    # --- Build model registry with provider's declared models ---
    registry = ModelRegistry()
    registry.register_defaults()

    _tier_map = {
        "strong": ModelTier.STRONG,
        "medium": ModelTier.MEDIUM,
        "light": ModelTier.LIGHT,
    }
    for tier_name, model_id in models_cfg.items():
        tier = _tier_map.get(tier_name)
        if tier and model_id:
            registry.register(RegisteredModel(
                model_id=model_id,
                provider=default_provider,
                tier=tier,
                cost_input_per_mtok=0.0,
                cost_output_per_mtok=0.0,
                speed="standard",
                context_window=128_000,
                max_output_tokens=8_192,
                capabilities=["code", "tool_use"],
            ))

    # --- Build raw gateway ---
    features = provider_cfg.get("features", {})
    thinking_budget: int | None = features.get("thinking_budget") or None

    if api_format == "anthropic":
        from hi_agent.llm.anthropic_gateway import AnthropicLLMGateway
        raw_gw: object = AnthropicLLMGateway(
            api_key_env=env_var,
            default_model=default_model or "claude-sonnet-4-6",
            timeout_seconds=120,
            base_url=base_url or "https://api.anthropic.com",
            default_thinking_budget=thinking_budget,
        )
    else:
        from hi_agent.llm.http_gateway import HttpLLMGateway
        raw_gw = HttpLLMGateway(
            base_url=base_url or "https://api.openai.com/v1",
            api_key_env=env_var,
            default_model=default_model or "gpt-4o",
            timeout_seconds=120,
        )

    tier_router = TierRouter(registry)
    return TierAwareLLMGateway(raw_gw, tier_router, registry)
