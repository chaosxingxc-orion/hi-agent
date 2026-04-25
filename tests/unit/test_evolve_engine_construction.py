"""Unit tests: EvolveEngine raises ValueError for each missing required injection.

Guards Rule 6 (H2-Track3) — all 3 inline fallback constructions removed:
  skill_extractor, regression_detector, champion_challenger.
Each must fail fast with a clear ValueError when not explicitly injected.
"""

from __future__ import annotations

import pytest
from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.regression_detector import RegressionDetector
from hi_agent.evolve.skill_extractor import SkillExtractor


def _base_kwargs() -> dict:
    """Return all required args so individual tests can omit one at a time."""
    return {
        "skill_extractor": SkillExtractor(),
        "regression_detector": RegressionDetector(),
        "champion_challenger": ChampionChallenger(),
    }


# ---------------------------------------------------------------------------
# skill_extractor
# ---------------------------------------------------------------------------


def test_engine_raises_on_missing_skill_extractor() -> None:
    """EvolveEngine must raise ValueError when skill_extractor=None.

    Rule 6: unscoped SkillExtractor inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["skill_extractor"] = None
    with pytest.raises(ValueError, match="skill_extractor"):
        EvolveEngine(**kwargs)


def test_engine_skill_extractor_error_mentions_rule6() -> None:
    """ValueError for missing skill_extractor must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["skill_extractor"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        EvolveEngine(**kwargs)


# ---------------------------------------------------------------------------
# regression_detector
# ---------------------------------------------------------------------------


def test_engine_raises_on_missing_regression_detector() -> None:
    """EvolveEngine must raise ValueError when regression_detector=None.

    Rule 6: unscoped RegressionDetector inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["regression_detector"] = None
    with pytest.raises(ValueError, match="regression_detector"):
        EvolveEngine(**kwargs)


def test_engine_regression_detector_error_mentions_rule6() -> None:
    """ValueError for missing regression_detector must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["regression_detector"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        EvolveEngine(**kwargs)


# ---------------------------------------------------------------------------
# champion_challenger
# ---------------------------------------------------------------------------


def test_engine_raises_on_missing_champion_challenger() -> None:
    """EvolveEngine must raise ValueError when champion_challenger=None.

    Rule 6: unscoped ChampionChallenger inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["champion_challenger"] = None
    with pytest.raises(ValueError, match="champion_challenger"):
        EvolveEngine(**kwargs)


def test_engine_champion_challenger_error_mentions_rule6() -> None:
    """ValueError for missing champion_challenger must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["champion_challenger"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        EvolveEngine(**kwargs)


# ---------------------------------------------------------------------------
# Positive: all args provided → construction succeeds
# ---------------------------------------------------------------------------


def test_engine_constructs_successfully_with_all_required_args() -> None:
    """EvolveEngine must construct without error when all 3 args are injected."""
    engine = EvolveEngine(
        skill_extractor=SkillExtractor(),
        regression_detector=RegressionDetector(),
        champion_challenger=ChampionChallenger(),
    )
    assert engine._skill_extractor is not None
    assert engine._regression_detector is not None
    assert engine._champion_challenger is not None
