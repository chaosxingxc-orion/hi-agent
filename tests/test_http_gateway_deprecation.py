"""Verify HttpLLMGateway emits DeprecationWarning in production profiles."""

from __future__ import annotations

import warnings

import pytest

from hi_agent.llm.http_gateway import HttpLLMGateway


def test_no_warning_dev_smoke() -> None:
    """No deprecation warning when runtime_mode is dev-smoke."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        HttpLLMGateway(runtime_mode="dev-smoke")
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 0


def test_no_warning_empty_mode() -> None:
    """No deprecation warning when runtime_mode is empty (legacy callers)."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        HttpLLMGateway(runtime_mode="")
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 0


def test_deprecation_warning_prod_real() -> None:
    """DeprecationWarning emitted when runtime_mode is prod-real."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        HttpLLMGateway(runtime_mode="prod-real")
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 1
    assert "HttpLLMGateway" in str(dep_warnings[0].message)
    assert "HTTPGateway" in str(dep_warnings[0].message)


def test_deprecation_warning_local_real() -> None:
    """DeprecationWarning emitted when runtime_mode is local-real."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        HttpLLMGateway(runtime_mode="local-real")
    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 1


def test_compat_sync_flag_suppresses_warning_in_cognition_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compat_sync_llm=True suppresses DeprecationWarning in cognition_builder."""
    monkeypatch.setenv("HI_AGENT_ENV", "prod")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.config.cognition_builder import CognitionBuilder
    import threading

    cfg = TraceConfig(compat_sync_llm=True, llm_default_provider="openai")
    builder = CognitionBuilder(cfg, threading.RLock())

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        gw = builder.build_llm_gateway()

    dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
    assert len(dep_warnings) == 0
    assert gw is not None
