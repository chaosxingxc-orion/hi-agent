"""Unit tests: SkillDefinition fail-fast on missing model under strict posture.

W32 Track B Gap 5 (W33 T-25'): the dataclass previously coerced an empty or
``"default"`` value to the string ``"default"`` on every construction. Under
research/prod posture this was a silent placeholder that masked configuration
errors. After W32 the coercion is dev-only; strict posture raises ValueError
so callers must supply a concrete model.

Layer 1 — Unit: pure SkillDefinition (no real LLM dependency).
"""

from __future__ import annotations

import pytest
from hi_agent.skill.definition import SkillDefinition


@pytest.fixture()
def baseline_kwargs() -> dict:
    """Construct the minimum kwargs to satisfy *other* validators."""
    return {
        "skill_id": "skill-x",
        "name": "x",
        "tenant_id": "tenant-A",
    }


class TestStrictModelRejection:
    """Under research/prod, missing/'default' model raises ValueError."""

    @pytest.mark.parametrize("posture_name", ["research", "prod"])
    def test_default_value_rejected_under_strict_posture(
        self, monkeypatch, baseline_kwargs, posture_name
    ):
        """Constructing with the dataclass default ``model="default"`` fails."""
        monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
        with pytest.raises(ValueError, match="model"):
            SkillDefinition(**baseline_kwargs)  # model defaults to "default"

    @pytest.mark.parametrize("posture_name", ["research", "prod"])
    def test_explicit_default_string_rejected_under_strict_posture(
        self, monkeypatch, baseline_kwargs, posture_name
    ):
        """Passing model='default' explicitly is also rejected."""
        monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
        with pytest.raises(ValueError, match="model"):
            SkillDefinition(model="default", **baseline_kwargs)

    @pytest.mark.parametrize("posture_name", ["research", "prod"])
    def test_empty_string_rejected_under_strict_posture(
        self, monkeypatch, baseline_kwargs, posture_name
    ):
        """Passing model='' is rejected (it would coerce under dev)."""
        monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
        with pytest.raises(ValueError, match="model"):
            SkillDefinition(model="", **baseline_kwargs)

    @pytest.mark.parametrize("posture_name", ["research", "prod"])
    def test_concrete_model_accepted_under_strict_posture(
        self, monkeypatch, baseline_kwargs, posture_name
    ):
        """A concrete model identifier passes strict posture."""
        monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
        skill = SkillDefinition(model="claude-opus-4-7", **baseline_kwargs)
        assert skill.model == "claude-opus-4-7"


class TestDevPostureCoercionPreserved:
    """Under dev posture the coercion + warning behaviour is preserved."""

    def test_default_value_coerced_with_warning(self, monkeypatch, caplog):
        """Dev posture keeps the ``"default"`` placeholder + WARNING."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        with caplog.at_level("WARNING", logger="hi_agent.skill.definition"):
            skill = SkillDefinition(skill_id="d1", name="d1")
        assert skill.model == "default"
        assert any(
            "model is empty or 'default'" in rec.getMessage() for rec in caplog.records
        ), "expected WARNING about coerced model under dev posture"

    def test_empty_model_coerced_to_default_under_dev(self, monkeypatch, caplog):
        """Empty model also coerces to 'default' with a WARNING."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        with caplog.at_level("WARNING", logger="hi_agent.skill.definition"):
            skill = SkillDefinition(skill_id="d2", name="d2", model="")
        assert skill.model == "default"

    def test_concrete_model_under_dev_posture(self, monkeypatch):
        """A concrete model under dev posture passes through unchanged."""
        monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
        skill = SkillDefinition(skill_id="d3", name="d3", model="claude-haiku")
        assert skill.model == "claude-haiku"
