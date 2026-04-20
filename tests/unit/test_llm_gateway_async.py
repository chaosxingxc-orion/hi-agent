"""Contract tests for CognitionBuilder.build_llm_gateway async branching (E-2).

When compat_sync_llm=False (the default), build_llm_gateway must NOT return
an HttpLLMGateway instance — it must use the async path (AsyncHTTPGateway or
TierAwareLLMGateway wrapping it).
"""
from __future__ import annotations

import os
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


def test_compat_sync_false_does_not_use_sync_gateway(mock_config, monkeypatch):
    """build_llm_gateway with compat_sync_llm=False must not return HttpLLMGateway."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-e2")
    monkeypatch.setenv("HI_AGENT_ENV", "dev")

    from hi_agent.config.cognition_builder import CognitionBuilder
    from hi_agent.llm.http_gateway import HttpLLMGateway

    builder = CognitionBuilder(
        config=mock_config,
        singleton_lock=threading.RLock(),
        skill_version_mgr_fn=lambda: None,
    )
    gateway = builder.build_llm_gateway()
    assert gateway is not None, "build_llm_gateway must return a gateway when API key is set"
    # Unwrap TierAwareLLMGateway if needed
    inner = getattr(gateway, "_inner", gateway)
    assert not isinstance(inner, HttpLLMGateway), (
        "build_llm_gateway with compat_sync_llm=False must not use HttpLLMGateway"
    )


def test_compat_sync_true_uses_sync_gateway(mock_config, monkeypatch):
    """build_llm_gateway with compat_sync_llm=True must use HttpLLMGateway."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-e2-sync")
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    mock_config.compat_sync_llm = True

    from hi_agent.config.cognition_builder import CognitionBuilder
    from hi_agent.llm.http_gateway import HttpLLMGateway

    builder = CognitionBuilder(
        config=mock_config,
        singleton_lock=threading.RLock(),
        skill_version_mgr_fn=lambda: None,
    )
    gateway = builder.build_llm_gateway()
    assert gateway is not None
    inner = getattr(gateway, "_inner", gateway)
    assert isinstance(inner, HttpLLMGateway), (
        "build_llm_gateway with compat_sync_llm=True must use HttpLLMGateway"
    )
