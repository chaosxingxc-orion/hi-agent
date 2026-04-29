"""Load LLM configuration from config/llm_config.json into TraceConfig.

Three public functions:

- ``load_from_json_config``: returns (TraceConfig, SystemBuilder) with env vars
  injected from the JSON file; suitable for callers that rely on
  SystemBuilder.build_llm_gateway() later.

- ``build_gateway_from_config``: builds a fully-wired TierAwareLLMGateway
  directly from the active provider entry in the JSON file, supporting
  arbitrary providers beyond the default anthropic/openai pair.

- ``get_provider_api_key``: returns the api_key for a named provider read
  exclusively from config/llm_config.json (no env-var fallback).

Usage::

    # Option A — full builder path
    from hi_agent.config.json_config_loader import load_from_json_config
    cfg, builder = load_from_json_config()
    gateway = builder.build_llm_gateway()

    # Option B — direct gateway from any provider
    from hi_agent.config.json_config_loader import build_gateway_from_config
    gateway = build_gateway_from_config()

    # Option C — check whether a provider has a key in config
    from hi_agent.config.json_config_loader import get_provider_api_key
    has_key = bool(get_provider_api_key("volces"))
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

_PROVIDER_BASE_URL_ENVS = {
    "anthropic": ("ANTHROPIC_BASE_URL", "HI_AGENT_ANTHROPIC_BASE_URL"),
    "openai": ("OPENAI_BASE_URL", "HI_AGENT_OPENAI_BASE_URL"),
    "volces": ("VOLCE_BASE_URL",),
}


def _provider_base_url_envs(provider: str) -> tuple[str, ...]:
    """Return provider-specific and generic base-url env names."""
    normalized = provider.strip().lower()
    generic = f"HI_AGENT_LLM_BASE_URL_{normalized.upper()}"
    names = [*_PROVIDER_BASE_URL_ENVS.get(normalized, ()), generic]
    return tuple(dict.fromkeys(names))


def _resolve_provider_api_key(provider: str, provider_cfg: dict) -> tuple[str, str]:
    """Resolve provider API key exclusively from config JSON.

    Returns ``(api_key, label)`` where ``label`` is a fixed string identifying
    the source ("config/llm_config.json").  Under research/prod posture an
    empty key raises ``ValueError``; under dev posture a warning is emitted.
    """
    from hi_agent.config.posture import Posture

    api_key = str(provider_cfg.get("api_key", "") or "")
    label = "config/llm_config.json"
    if not api_key:
        posture = Posture.from_env()
        if posture.is_strict:
            raise ValueError(
                f"api_key required for provider {provider!r} under posture {posture}; "
                "populate config/llm_config.json"
            )
        _logger.warning(
            "json_config_loader: provider %r has no api_key in config/llm_config.json "
            "(posture=%s — continuing in dev mode)",
            provider,
            posture,
        )
    return api_key, label


def get_provider_api_key(
    provider: str,
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
) -> str:
    """Return the api_key for *provider* from config/llm_config.json only.

    No environment-variable fallback.  Returns an empty string when the
    config file does not exist or the provider has no ``api_key`` field.
    """
    path = Path(config_path)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    providers = data.get("providers", {})
    provider_cfg = providers.get(provider.strip().lower(), {})
    return str(provider_cfg.get("api_key", "") or "")


def _resolve_provider_base_url(provider: str, provider_cfg: dict) -> str:
    """Resolve provider base URL, allowing env to override JSON."""
    for env_name in _provider_base_url_envs(provider):
        value = os.environ.get(env_name, "")
        if value:
            return value
    return str(provider_cfg.get("base_url", "") or "")


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

    api_key, _ = _resolve_provider_api_key(default_provider, provider_cfg)
    if not api_key:
        _logger.warning(
            "build_gateway_from_config: provider %r has no api_key in config/llm_config.json",
            default_provider,
        )
        return None

    api_format = provider_cfg.get("api_format", "anthropic")
    # Env var takes priority (allows structural gate / local override to redirect base URL).
    # Fall back to anthropic_base_url for Anthropic-format providers (AnthropicLLMGateway
    # appends /v1/messages itself, so base_url must not include /v1).
    _env_base_url: str | None = None
    for _env_name in _provider_base_url_envs(default_provider):
        _val = os.environ.get(_env_name)
        if _val:
            _env_base_url = _val
            break
    if _env_base_url is not None:
        base_url = _env_base_url
    elif api_format == "anthropic" and provider_cfg.get("anthropic_base_url"):
        base_url = str(provider_cfg["anthropic_base_url"])
    else:
        base_url = _resolve_provider_base_url(default_provider, provider_cfg)
    models_cfg = provider_cfg.get("models", {})
    default_model = (
        models_cfg.get("strong") or models_cfg.get("medium") or models_cfg.get("light") or ""
    )

    # Inject API key into a temporary env var consumed by gateway constructors.
    # We use a private env-var name to avoid polluting standard names.
    # The env var is restored after construction so gateways cache the key at
    # construction time (AnthropicLLMGateway._api_key_resolved).
    _tmp_env_var = f"_HI_AGENT_TMP_KEY_{default_provider.upper()}"
    _prev_env_val = os.environ.get(_tmp_env_var)
    os.environ[_tmp_env_var] = api_key
    _logger.info(
        "build_gateway_from_config: provider=%r format=%r key_source=config/llm_config.json",
        default_provider,
        api_format,
    )

    try:
        # --- Build model registry with provider's declared models only ---
        # Do not call register_defaults(): that would inject gpt-4.1 / claude-sonnet
        # defaults and mix them with third-party provider models in the registry.
        registry = ModelRegistry()

        _tier_map = {
            "strong": ModelTier.STRONG,
            "medium": ModelTier.MEDIUM,
            "light": ModelTier.LIGHT,
        }
        for tier_name, model_id in models_cfg.items():
            tier = _tier_map.get(tier_name)
            if tier and model_id and registry.get(model_id) is None:
                registry.register(
                    RegisteredModel(
                        model_id=model_id,
                        provider=default_provider,
                        tier=tier,
                        cost_input_per_mtok=0.0,
                        cost_output_per_mtok=0.0,
                        speed="standard",
                        context_window=128_000,
                        max_output_tokens=8_192,
                        capabilities=["code", "tool_use"],
                    )
                )

        # --- Build raw gateway ---
        features = provider_cfg.get("features", {})
        thinking_budget: int | None = features.get("thinking_budget") or None
        _timeout = int(provider_cfg.get("timeout_seconds", 120))

        if api_format == "anthropic":
            from hi_agent.llm.anthropic_gateway import AnthropicLLMGateway

            raw_gw: object = AnthropicLLMGateway(
                api_key_env=_tmp_env_var,
                default_model=default_model or "claude-sonnet-4-6",
                timeout_seconds=_timeout,
                base_url=base_url or "https://api.anthropic.com",
                default_thinking_budget=thinking_budget,
            )
        else:
            from hi_agent.llm.http_gateway import HttpLLMGateway

            raw_gw = HttpLLMGateway(
                base_url=base_url or "https://api.openai.com/v1",
                api_key_env=_tmp_env_var,
                default_model=default_model or "gpt-4o",
                timeout_seconds=_timeout,
            )

        tier_router = TierRouter(registry)
        result = TierAwareLLMGateway(raw_gw, tier_router, registry)
    finally:
        # Restore env var to its prior state after the gateway has cached the key.
        if _prev_env_val is None:
            os.environ.pop(_tmp_env_var, None)
        else:
            os.environ[_tmp_env_var] = _prev_env_val
    return result
