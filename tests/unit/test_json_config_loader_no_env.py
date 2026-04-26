"""Tests for API key config-only loading (W5-A: no env-var fallback).

Rule 11 coverage: dev posture allows missing key; research posture raises.
Rule 6 coverage: no inline fallback — key must come from config JSON only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest


def _write_config(path: Path, api_key: str = "") -> None:
    path.write_text(
        json.dumps(
            {
                "default_provider": "volces",
                "providers": {
                    "volces": {
                        "api_key": api_key,
                        "base_url": "https://cfg.example/api/v1",
                        "api_format": "openai",
                        "timeout_seconds": 60,
                        "models": {"strong": "doubao-test-model"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. research posture + empty api_key → ValueError
# ---------------------------------------------------------------------------


def test_empty_api_key_raises_under_research_posture(tmp_path: Path, monkeypatch) -> None:
    """Under research posture, an empty api_key must raise ValueError."""
    from hi_agent.config.json_config_loader import _resolve_provider_api_key

    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    # Ensure VOLCE_API_KEY is absent so no env fallback is possible.
    monkeypatch.delenv("VOLCE_API_KEY", raising=False)

    with pytest.raises(ValueError, match="api_key required for provider"):
        _resolve_provider_api_key("volces", {"api_key": ""})


def test_empty_api_key_raises_under_prod_posture(tmp_path: Path, monkeypatch) -> None:
    """Under prod posture, an empty api_key must also raise ValueError."""
    from hi_agent.config.json_config_loader import _resolve_provider_api_key

    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    monkeypatch.delenv("VOLCE_API_KEY", raising=False)

    with pytest.raises(ValueError, match="api_key required for provider"):
        _resolve_provider_api_key("volces", {"api_key": ""})


# ---------------------------------------------------------------------------
# 2. dev posture + empty api_key → warning only, no exception
# ---------------------------------------------------------------------------


def test_empty_api_key_warns_under_dev_posture(monkeypatch, caplog) -> None:
    """Under dev posture, an empty api_key emits a WARNING but does not raise."""
    from hi_agent.config.json_config_loader import _resolve_provider_api_key

    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.delenv("VOLCE_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING, logger="hi_agent.config.json_config_loader"):
        key, label = _resolve_provider_api_key("volces", {"api_key": ""})

    assert key == ""
    assert label == "config/llm_config.json"
    assert any("no api_key" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 3. VOLCE_API_KEY env var set → loader does NOT use it
# ---------------------------------------------------------------------------


def test_loader_ignores_volce_api_key_env_var(tmp_path: Path, monkeypatch) -> None:
    """Even when VOLCE_API_KEY is present in the environment, the loader must
    not use it — keys come exclusively from config/llm_config.json."""
    from hi_agent.config.json_config_loader import get_provider_api_key

    cfg_path = tmp_path / "llm_config.json"
    _write_config(cfg_path, api_key="config-key-only")

    # Simulate a stale env var that should be ignored.
    monkeypatch.setenv("VOLCE_API_KEY", "env-key-should-be-ignored")

    result = get_provider_api_key("volces", cfg_path)

    # Must come from config, not from env.
    assert result == "config-key-only"
    assert result != "env-key-should-be-ignored"


def test_loader_returns_empty_when_config_has_no_key(tmp_path: Path, monkeypatch) -> None:
    """get_provider_api_key returns empty string when config api_key is blank,
    even if VOLCE_API_KEY env var is non-empty."""
    from hi_agent.config.json_config_loader import get_provider_api_key

    cfg_path = tmp_path / "llm_config.json"
    _write_config(cfg_path, api_key="")

    monkeypatch.setenv("VOLCE_API_KEY", "env-key-should-be-ignored")

    result = get_provider_api_key("volces", cfg_path)

    assert result == ""


def test_loader_returns_empty_when_config_missing(tmp_path: Path, monkeypatch) -> None:
    """get_provider_api_key returns empty string when the config file does not exist."""
    from hi_agent.config.json_config_loader import get_provider_api_key

    monkeypatch.setenv("VOLCE_API_KEY", "env-key-should-be-ignored")

    result = get_provider_api_key("volces", tmp_path / "nonexistent.json")

    assert result == ""


# ---------------------------------------------------------------------------
# 4. build_gateway_from_config reads key from config only
# ---------------------------------------------------------------------------


def test_build_gateway_reads_key_from_config_only(tmp_path: Path, monkeypatch) -> None:
    """build_gateway_from_config must use the config JSON api_key, not env vars."""
    from hi_agent.config.json_config_loader import build_gateway_from_config

    cfg_path = tmp_path / "llm_config.json"
    _write_config(cfg_path, api_key="config-gateway-key")
    # Even with VOLCE_API_KEY set, the gateway should still build from config.
    monkeypatch.setenv("VOLCE_API_KEY", "env-key-should-be-ignored")
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    gateway = build_gateway_from_config(cfg_path)

    assert gateway is not None


def test_build_gateway_returns_none_when_config_key_absent(
    tmp_path: Path, monkeypatch
) -> None:
    """build_gateway_from_config returns None when the config has no api_key,
    regardless of env var state (dev posture to avoid ValueError)."""
    from hi_agent.config.json_config_loader import build_gateway_from_config

    cfg_path = tmp_path / "llm_config.json"
    _write_config(cfg_path, api_key="")
    monkeypatch.delenv("VOLCE_API_KEY", raising=False)
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    gateway = build_gateway_from_config(cfg_path)

    assert gateway is None
