"""Evolve subsystem -- the 'E' in TRACE.

Provides post-run analysis, skill extraction, regression detection, and
champion/challenger comparison to drive continuous agent improvement.
"""

from hi_agent.evolve.champion_challenger import ChampionChallenger, ComparisonResult
from hi_agent.evolve.contracts import (
    EvolveChange,
    EvolveMetrics,
    EvolveResult,
    RunPostmortem,
)
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.postmortem import PostmortemAnalyzer
from hi_agent.evolve.regression_detector import RegressionDetector, RegressionReport
from hi_agent.evolve.skill_extractor import SkillCandidate, SkillExtractor

__all__ = [
    "ChampionChallenger",
    "ComparisonResult",
    "EvolveChange",
    "EvolveEngine",
    "EvolveMetrics",
    "EvolveResult",
    "PostmortemAnalyzer",
    "RegressionDetector",
    "RegressionReport",
    "RunPostmortem",
    "SkillCandidate",
    "SkillExtractor",
]
