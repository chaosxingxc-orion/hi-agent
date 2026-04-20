"""Tests for live LLM integration model selection."""

from __future__ import annotations

from tests.integration import test_live_llm_api as live_llm_api


def test_behavior_models_default_to_production_route_models(monkeypatch):
    """Behavior checks should use configured route models, not the full catalog."""
    monkeypatch.delenv("VOLCE_LIVE_BEHAVIOR_MODELS", raising=False)
    monkeypatch.setattr(
        live_llm_api,
        "_vcfg",
        {"models": {"strong": "doubao-pro", "medium": "doubao-lite", "light": "doubao-lite"}},
    )
    monkeypatch.setattr(live_llm_api, "_ALL_MODELS", ["doubao-pro", "doubao-lite", "kimi"])

    assert live_llm_api._behavior_models() == ["doubao-pro", "doubao-lite"]


def test_behavior_models_can_be_expanded_to_full_catalog(monkeypatch):
    """Manual runs can still opt into the full behavior matrix."""
    monkeypatch.setenv("VOLCE_LIVE_BEHAVIOR_MODELS", "all")
    monkeypatch.setattr(live_llm_api, "_ALL_MODELS", ["doubao-pro", "kimi"])

    assert live_llm_api._behavior_models() == ["doubao-pro", "kimi"]
