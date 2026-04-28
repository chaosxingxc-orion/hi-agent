"""Unit tests for apply_strict_defaults in tier_presets.

Verifies that platform purpose -> tier mappings are correctly
registered on a TierRouter instance without clobbering existing defaults.
"""

from __future__ import annotations

from hi_agent.llm.registry import ModelRegistry, ModelTier
from hi_agent.llm.tier_presets import apply_strict_defaults
from hi_agent.llm.tier_router import TierRouter


def _make_router() -> TierRouter:
    """Return a TierRouter with an empty (no registered models) registry."""
    registry = ModelRegistry()
    return TierRouter(registry)


def test_pi_agent_is_strong() -> None:
    """pi_agent purpose should map to strong tier after applying strict defaults."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("pi_agent") == ModelTier.STRONG


def test_lean_proof_is_strong() -> None:
    """lean_proof purpose should map to strong tier."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("lean_proof") == ModelTier.STRONG


def test_paper_writing_is_strong() -> None:
    """paper_writing purpose should map to strong tier."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("paper_writing") == ModelTier.STRONG


def test_peer_review_is_strong() -> None:
    """peer_review purpose should map to strong tier."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("peer_review") == ModelTier.STRONG


def test_survey_synthesis_is_medium() -> None:
    """survey_synthesis purpose should map to medium tier."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("survey_synthesis") == ModelTier.MEDIUM


def test_experiment_design_is_medium() -> None:
    """experiment_design purpose should map to medium tier."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("experiment_design") == ModelTier.MEDIUM


def test_experiment_eval_is_medium() -> None:
    """experiment_eval purpose should map to medium tier."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("experiment_eval") == ModelTier.MEDIUM


def test_survey_fetch_is_light() -> None:
    """survey_fetch purpose should map to light tier after applying strict defaults."""
    router = _make_router()
    apply_strict_defaults(router)
    assert router.get_tier_for_purpose("survey_fetch") == ModelTier.LIGHT


def test_existing_perception_not_clobbered() -> None:
    """Applying strict defaults must not change the built-in perception mapping."""
    router = _make_router()
    before = router.get_tier_for_purpose("perception")
    apply_strict_defaults(router)
    after = router.get_tier_for_purpose("perception")
    assert before == after == ModelTier.LIGHT


def test_existing_control_not_clobbered() -> None:
    """Applying strict defaults must not change the built-in control mapping."""
    router = _make_router()
    before = router.get_tier_for_purpose("control")
    apply_strict_defaults(router)
    after = router.get_tier_for_purpose("control")
    assert before == after == ModelTier.MEDIUM


def test_pi_agent_allow_upgrade_false() -> None:
    """pi_agent should have allow_upgrade=False (locked to strong, cannot be upgraded further)."""
    router = _make_router()
    apply_strict_defaults(router)
    with router._lock:
        mapping = router._tier_map["pi_agent"]
    assert mapping.allow_upgrade is False
    assert mapping.allow_downgrade is False


def test_survey_fetch_allow_downgrade_false() -> None:
    """survey_fetch should have allow_downgrade=False (already light, must not go lower)."""
    router = _make_router()
    apply_strict_defaults(router)
    with router._lock:
        mapping = router._tier_map["survey_fetch"]
    assert mapping.allow_downgrade is False
    assert mapping.allow_upgrade is True
