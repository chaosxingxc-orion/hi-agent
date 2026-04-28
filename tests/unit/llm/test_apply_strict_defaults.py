"""Tests for apply_strict_defaults canonical function."""
from __future__ import annotations

from hi_agent.llm.registry import ModelRegistry, ModelTier
from hi_agent.llm.tier_router import TierRouter


def _make_router() -> TierRouter:
    """Return a TierRouter with an empty registry."""
    return TierRouter(ModelRegistry())


def test_apply_strict_defaults_exists():
    from hi_agent.llm import apply_strict_defaults

    assert callable(apply_strict_defaults)


def test_apply_strict_defaults_pi_agent_strong():
    """apply_strict_defaults maps pi_agent to strong tier."""
    from hi_agent.llm import apply_strict_defaults

    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("pi_agent") == ModelTier.STRONG


def test_apply_strict_defaults_survey_fetch_light():
    """apply_strict_defaults maps survey_fetch to light tier."""
    from hi_agent.llm import apply_strict_defaults

    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("survey_fetch") == ModelTier.LIGHT
