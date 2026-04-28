"""Domain-specific TierRouter presets."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.llm.tier_router import TierRouter


def apply_strict_defaults(tier_router: TierRouter) -> None:
    """Apply strict platform tier defaults to a TierRouter instance.

    Call this once after constructing TierRouter to configure
    purpose → tier mappings optimized for strict/research posture:

        pi_agent           → strong  (planning, judgment, cross-project reasoning)
        lean_proof         → strong  (formal verification, no downgrade)
        paper_writing      → strong  (synthesis, argument construction)
        peer_review        → strong  (quality judgment)
        survey_synthesis   → medium  (moderate reasoning over gathered sources)
        experiment_design  → medium  (structured methodology)
        experiment_eval    → medium  (result interpretation)
        survey_fetch       → light   (extraction, structured lookup)
    """
    tier_router.set_tier("pi_agent", "strong", allow_upgrade=False, allow_downgrade=False)
    tier_router.set_tier("lean_proof", "strong", allow_upgrade=False, allow_downgrade=False)
    tier_router.set_tier("paper_writing", "strong", allow_upgrade=False, allow_downgrade=False)
    tier_router.set_tier("peer_review", "strong", allow_upgrade=False, allow_downgrade=False)
    tier_router.set_tier("survey_synthesis", "medium", allow_upgrade=True, allow_downgrade=True)
    tier_router.set_tier("experiment_design", "medium", allow_upgrade=True, allow_downgrade=True)
    tier_router.set_tier("experiment_eval", "medium", allow_upgrade=True, allow_downgrade=True)
    tier_router.set_tier("survey_fetch", "light", allow_upgrade=True, allow_downgrade=False)


