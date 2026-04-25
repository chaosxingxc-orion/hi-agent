"""Unit tests for hi_agent.config.posture — Posture enum and from_env."""

from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


class TestPostureFromEnv:
    def test_default_is_dev(self, monkeypatch):
        monkeypatch.delenv("HI_AGENT_POSTURE", raising=False)
        assert Posture.from_env() == Posture.DEV

    def test_dev_explicit(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        assert Posture.from_env() == Posture.DEV

    def test_research(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        assert Posture.from_env() == Posture.RESEARCH

    def test_prod(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
        assert Posture.from_env() == Posture.PROD

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "RESEARCH")
        assert Posture.from_env() == Posture.RESEARCH

    def test_unknown_value_raises(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "staging")
        with pytest.raises(ValueError, match="HI_AGENT_POSTURE"):
            Posture.from_env()

    def test_empty_string_raises(self, monkeypatch):
        monkeypatch.setenv("HI_AGENT_POSTURE", "")
        with pytest.raises(ValueError, match="HI_AGENT_POSTURE"):
            Posture.from_env()


class TestPostureIsStrict:
    def test_dev_is_not_strict(self):
        assert Posture.DEV.is_strict is False

    def test_research_is_strict(self):
        assert Posture.RESEARCH.is_strict is True

    def test_prod_is_strict(self):
        assert Posture.PROD.is_strict is True


class TestPostureRequiresProperties:
    """All requires_* properties follow is_strict — False for dev, True for strict."""

    @pytest.mark.parametrize("prop", [
        "requires_project_id",
        "requires_profile_id",
        "requires_durable_queue",
        "requires_durable_ledger",
        "requires_durable_registry",
        "requires_strict_profile_schema",
        "requires_authenticated_idempotency_scope",
    ])
    def test_dev_all_false(self, prop):
        assert getattr(Posture.DEV, prop) is False

    @pytest.mark.parametrize("prop", [
        "requires_project_id",
        "requires_profile_id",
        "requires_durable_queue",
        "requires_durable_ledger",
        "requires_durable_registry",
        "requires_strict_profile_schema",
        "requires_authenticated_idempotency_scope",
    ])
    @pytest.mark.parametrize("posture", [Posture.RESEARCH, Posture.PROD])
    def test_strict_postures_all_true(self, posture, prop):
        assert getattr(posture, prop) is True


class TestGetPosture:
    def test_get_posture_delegates_to_from_env(self, monkeypatch):
        from hi_agent.config.runtime_config_loader import get_posture
        monkeypatch.setenv("HI_AGENT_POSTURE", "research")
        assert get_posture() == Posture.RESEARCH
