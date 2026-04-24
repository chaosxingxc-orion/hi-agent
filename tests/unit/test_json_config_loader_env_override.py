"""Config-file LLM gateway environment override tests."""

from __future__ import annotations

import json
from pathlib import Path


def _write_volces_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "default_provider": "volces",
                "providers": {
                    "volces": {
                        "api_key": "",
                        "base_url": "https://cfg.example/api/coding/v1",
                        "api_format": "openai",
                        "timeout_seconds": 60,
                        "models": {
                            "strong": "doubao-seed-2.0-pro",
                            "medium": "doubao-seed-2.0-lite",
                            "light": "doubao-seed-2.0-lite",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_build_gateway_from_config_uses_volce_api_key_env_when_json_key_blank(
    tmp_path: Path, monkeypatch
) -> None:
    """The production config path must accept secrets from the environment."""
    from hi_agent.config.json_config_loader import build_gateway_from_config

    config_path = tmp_path / "llm_config.json"
    _write_volces_config(config_path)
    monkeypatch.setenv("VOLCE_API_KEY", "env-volces-key")

    gateway = build_gateway_from_config(config_path)

    assert gateway is not None
    registry = gateway._registry
    providers = {model.provider for model in registry.list_all()}
    assert providers == {"volces"}


def test_build_gateway_from_config_prefers_strong_model_as_default(
    tmp_path: Path, monkeypatch
) -> None:
    """The raw gateway default should avoid medium reasoning-only smoke failures."""
    from hi_agent.config.json_config_loader import build_gateway_from_config

    config_path = tmp_path / "llm_config.json"
    _write_volces_config(config_path)
    monkeypatch.setenv("VOLCE_API_KEY", "env-volces-key")

    gateway = build_gateway_from_config(config_path)

    assert gateway is not None
    assert gateway._inner._default_model == "doubao-seed-2.0-pro"


def test_system_builder_activates_config_provider_with_volce_env_key(
    tmp_path: Path, monkeypatch
) -> None:
    """SystemBuilder must not require the secret to be written into JSON."""
    import hi_agent.config.json_config_loader as loader
    from hi_agent.config.builder import SystemBuilder

    config_path = tmp_path / "llm_config.json"
    _write_volces_config(config_path)
    monkeypatch.setattr(loader, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setenv("VOLCE_API_KEY", "env-volces-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    builder = SystemBuilder()
    gateway = builder.build_llm_gateway()

    assert gateway is not None
    registry = gateway._registry
    providers = {model.provider for model in registry.list_all()}
    assert providers == {"volces"}
