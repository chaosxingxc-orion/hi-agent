"""Tests for secret-safe live LLM config loading."""

from __future__ import annotations

import json
from pathlib import Path

from tests.helpers import live_llm_config as live_cfg


def _write_config(tmp_path: Path, *, api_key: str = "cfg-key") -> Path:
    path = tmp_path / "llm_config.json"
    path.write_text(
        json.dumps(
            {
                "default_provider": "volces",
                "providers": {
                    "volces": {
                        "api_key": api_key,
                        "base_url": "https://cfg.example/v1",
                        "timeout_seconds": 11,
                        "max_retries": 2,
                        "models": {"strong": "cfg-strong", "medium": "cfg-model"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_live_llm_config_reads_json_and_env_overrides(tmp_path, monkeypatch):
    """Env overrides should win over JSON values without exposing secrets."""
    path = _write_config(tmp_path)
    monkeypatch.setenv("VOLCE_API_KEY", "env-key")
    monkeypatch.setenv("VOLCE_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("VOLCE_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("VOLCE_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("VOLCE_MAX_RETRIES", "4")

    cfg = live_cfg.load_live_llm_config(config_path=path)

    assert cfg.provider == "volces"
    assert cfg.api_key == "env-key"
    assert cfg.base_url == "https://env.example/v1"
    assert cfg.default_model == "env-model"
    assert cfg.timeout_seconds == 17.0
    assert cfg.max_retries == 4
    assert cfg.enabled is True
    assert "env-key" not in repr(cfg)
    assert "env-key" not in str(cfg)


def test_live_llm_config_forces_heuristic_mode(tmp_path, monkeypatch):
    """Heuristic mode must disable live use even when credentials exist."""
    path = _write_config(tmp_path)
    monkeypatch.delenv("VOLCE_API_KEY", raising=False)
    monkeypatch.setenv("HI_AGENT_LLM_MODE", "heuristic")

    cfg = live_cfg.load_live_llm_config(config_path=path)

    assert cfg.mode == "heuristic"
    assert cfg.live_enabled is False
    assert cfg.enabled is False


def test_live_llm_config_prefers_strong_model_for_live_smoke(tmp_path, monkeypatch):
    """Live smoke calls use the strongest configured model by default."""
    path = _write_config(tmp_path)
    monkeypatch.delenv("VOLCE_DEFAULT_MODEL", raising=False)

    cfg = live_cfg.load_live_llm_config(config_path=path)

    assert cfg.default_model == "cfg-strong"


def test_live_llm_config_allows_real_and_volces_modes_with_credentials(tmp_path, monkeypatch):
    """Real and volces modes should enable live calls when a key is available."""
    path = _write_config(tmp_path)

    monkeypatch.setenv("HI_AGENT_LLM_MODE", "real")
    cfg_real = live_cfg.load_live_llm_config(config_path=path)
    assert cfg_real.mode == "real"
    assert cfg_real.live_enabled is True

    monkeypatch.setenv("HI_AGENT_LLM_MODE", "volces")
    cfg_volces = live_cfg.load_live_llm_config(config_path=path)
    assert cfg_volces.mode == "volces"
    assert cfg_volces.live_enabled is True


def test_live_llm_config_requires_a_credential_for_live_modes(tmp_path, monkeypatch):
    """Live modes should not activate without a usable credential."""
    path = _write_config(tmp_path, api_key="")
    monkeypatch.setenv("HI_AGENT_LLM_MODE", "real")
    monkeypatch.delenv("VOLCE_API_KEY", raising=False)

    cfg = live_cfg.load_live_llm_config(config_path=path)

    assert cfg.mode == "real"
    assert cfg.live_enabled is False
    assert cfg.enabled is False
