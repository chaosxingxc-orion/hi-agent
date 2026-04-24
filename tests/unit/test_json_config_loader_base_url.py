"""Unit tests for json_config_loader base_url selection (Wave 1, W1-3).

Verifies that build_gateway_from_config uses anthropic_base_url when
api_format=='anthropic' and that base_url is used otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def _write_config(tmp_path: Path, provider_cfg: dict, api_format: str = "anthropic") -> Path:
    """Write a minimal llm_config.json for the given provider config."""
    cfg = {
        "default_provider": "test-provider",
        "providers": {
            "test-provider": {
                "api_key": "sk-test",
                "api_format": api_format,
                **provider_cfg,
                "models": {"strong": "test-model", "medium": "test-model-m"},
            }
        },
    }
    path = tmp_path / "llm_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


class TestBaseUrlSelection:
    """base_url selection in build_gateway_from_config."""

    def test_anthropic_format_uses_anthropic_base_url(self, tmp_path: Path) -> None:
        """When api_format=='anthropic' and anthropic_base_url is set, it is used."""
        cfg_path = _write_config(
            tmp_path,
            {
                "anthropic_base_url": "https://custom.host/api",
                "base_url": "https://wrong.host/v1",
            },
            api_format="anthropic",
        )

        with patch("hi_agent.llm.anthropic_gateway.AnthropicLLMGateway") as mock_cls:
            mock_cls.return_value = MagicMock()
            from hi_agent.config.json_config_loader import build_gateway_from_config

            build_gateway_from_config(cfg_path)
            assert mock_cls.called, "AnthropicLLMGateway should have been constructed"
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs.get("base_url") == "https://custom.host/api", (
                f"Expected anthropic_base_url to be used, got: {call_kwargs.get('base_url')}"
            )

    def test_anthropic_format_falls_back_to_base_url(self, tmp_path: Path) -> None:
        """When api_format=='anthropic' but only base_url is set, base_url is used."""
        cfg_path = _write_config(
            tmp_path,
            {"base_url": "https://fallback.host/v1"},
            api_format="anthropic",
        )

        with patch("hi_agent.llm.anthropic_gateway.AnthropicLLMGateway") as mock_cls:
            mock_cls.return_value = MagicMock()
            from hi_agent.config.json_config_loader import build_gateway_from_config

            build_gateway_from_config(cfg_path)
            assert mock_cls.called
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs.get("base_url") == "https://fallback.host/v1", (
                f"Expected base_url fallback, got: {call_kwargs.get('base_url')}"
            )

    def test_openai_format_uses_base_url_even_if_anthropic_base_url_present(
        self, tmp_path: Path
    ) -> None:
        """When api_format=='openai', base_url is used (anthropic_base_url ignored)."""
        cfg_path = _write_config(
            tmp_path,
            {
                "base_url": "https://openai-compat.host/v1",
                "anthropic_base_url": "https://should-be-ignored.host",
            },
            api_format="openai",
        )

        with patch("hi_agent.llm.http_gateway.HttpLLMGateway") as mock_cls:
            mock_cls.return_value = MagicMock()
            from hi_agent.config.json_config_loader import build_gateway_from_config

            build_gateway_from_config(cfg_path)
            assert mock_cls.called, "HttpLLMGateway should have been constructed for openai format"
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs.get("base_url") == "https://openai-compat.host/v1", (
                f"Expected base_url for openai format, got: {call_kwargs.get('base_url')}"
            )
