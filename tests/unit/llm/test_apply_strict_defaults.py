"""Tests for apply_strict_defaults canonical function and apply_research_defaults shim."""
from __future__ import annotations

import warnings

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


def test_apply_research_defaults_emits_deprecation():
    from hi_agent.llm import apply_research_defaults

    router = _make_router()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        apply_research_defaults(router)
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "apply_research_defaults must emit DeprecationWarning"
    assert "Wave 12" in str(dep_warns[0].message)
    assert "apply_strict_defaults" in str(dep_warns[0].message)


def test_apply_strict_defaults_and_apply_research_defaults_produce_same_effect():
    """Both functions must produce identical TierRouter state."""
    from hi_agent.llm import apply_research_defaults, apply_strict_defaults

    router_strict = _make_router()
    router_research = _make_router()

    apply_strict_defaults(router_strict)
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        apply_research_defaults(router_research)

    # Compare tier maps for each purpose set by the presets
    purposes = [
        "pi_agent",
        "lean_proof",
        "paper_writing",
        "peer_review",
        "survey_synthesis",
        "experiment_design",
        "experiment_eval",
        "survey_fetch",
    ]
    for purpose in purposes:
        t_strict = router_strict.get_tier_for_purpose(purpose)
        t_research = router_research.get_tier_for_purpose(purpose)
        assert t_strict == t_research, (
            f"Purpose {purpose!r}: apply_strict_defaults gave {t_strict!r} "
            f"but apply_research_defaults gave {t_research!r}"
        )
