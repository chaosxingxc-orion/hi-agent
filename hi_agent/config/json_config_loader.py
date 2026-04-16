"""Load LLM configuration from config/llm_config.json into TraceConfig.

Usage::

    from hi_agent.config.json_config_loader import load_from_json_config

    cfg, builder = load_from_json_config()
    gateway = builder.build_llm_gateway()
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

_logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "llm_config.json"


def load_from_json_config(
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
) -> tuple[TraceConfig, SystemBuilder]:
    """Read llm_config.json, inject API keys into env, return (TraceConfig, SystemBuilder).

    If the config file does not exist, returns a default TraceConfig and SystemBuilder
    without injecting any keys.

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
