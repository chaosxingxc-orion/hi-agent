"""Contract tests for CognitionBuilder.build_llm_gateway stable sync path.

DF-38 is deferred: current shippable Rule 15 evidence is on the sync
HttpLLMGateway path. Async HTTPGateway coverage belongs in a dedicated future
gate, not this stable production contract.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def mock_config():
    """Minimal TraceConfig-like object with an OpenAI API key set."""
    cfg = MagicMock()
    cfg.openai_api_key_env = "OPENAI_API_KEY"
    cfg.anthropic_api_key_env = "ANTHROPIC_API_KEY"
    cfg.openai_base_url = "https://api.openai.com/v1"
    cfg.openai_default_model = "gpt-4o"
    cfg.anthropic_base_url = "https://api.anthropic.com/v1"
    cfg.anthropic_default_model = "claude-3-5-sonnet-20241022"
    cfg.llm_timeout_seconds = 30
    cfg.llm_default_provider = "openai"
    cfg.llm_mode = "real"
    cfg.kernel_mode = "http"
    cfg.compat_sync_llm = False
    cfg.llm_budget_max_calls = 0
    cfg.llm_budget_max_tokens = 0
    cfg.skill_dirs = []
    return cfg


def _build_gateway(config):
    from hi_agent.config.cognition_builder import CognitionBuilder

    builder = CognitionBuilder(
        config=config,
        singleton_lock=threading.RLock(),
        skill_version_mgr_fn=lambda: None,
    )
    return builder.build_llm_gateway()


def _inner_gateway(gateway):
    return getattr(gateway, "_inner", gateway)


def test_compat_sync_false_still_uses_stable_sync_gateway(mock_config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-e2")
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    # Isolate from the real llm_config.json so the env-var path is exercised.
    import hi_agent.config.json_config_loader as _jcl

    monkeypatch.setattr(_jcl, "_DEFAULT_CONFIG_PATH", "/nonexistent/llm_config.json")

    from hi_agent.llm.async_http_gateway import AsyncHTTPGateway

    gateway = _build_gateway(mock_config)

    assert gateway is not None, "build_llm_gateway must return a gateway when API key is set"
    assert isinstance(_inner_gateway(gateway), AsyncHTTPGateway), (
        "compat_sync_llm=False (default) must use AsyncHTTPGateway"
    )


def test_compat_sync_true_uses_sync_gateway(mock_config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-e2-sync")
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    mock_config.compat_sync_llm = True
    # Isolate from the real llm_config.json so the env-var path is exercised.
    import hi_agent.config.json_config_loader as _jcl

    monkeypatch.setattr(_jcl, "_DEFAULT_CONFIG_PATH", "/nonexistent/llm_config.json")

    from hi_agent.llm.http_gateway import HttpLLMGateway

    gateway = _build_gateway(mock_config)

    assert gateway is not None
    assert isinstance(_inner_gateway(gateway), HttpLLMGateway), (
        "build_llm_gateway with compat_sync_llm=True must use HttpLLMGateway"
    )
