"""Evolve subsystem -- the 'E' in TRACE.

Provides post-run analysis, skill extraction, regression detection, and
champion/challenger comparison to drive continuous agent improvement.
"""

from hi_agent.evolve.champion_challenger import ChampionChallenger, ComparisonResult
from hi_agent.evolve.contracts import (
    EvolveChange,
    EvolveMetrics,
    EvolveResult,
    RunRetrospective,
)
from hi_agent.evolve.dataset_evaluator import DatasetEvaluator, SkillPromotionPipeline
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.evolve.regression_detector import RegressionDetector, RegressionReport
from hi_agent.evolve.retrospective import PostmortemAnalyzer
from hi_agent.evolve.skill_extractor import SkillCandidate, SkillExtractor

__all__ = [
    "ChampionChallenger",
    "ComparisonResult",
    "DatasetEvaluator",
    "EvolveChange",
    "EvolveEngine",
    "EvolveMetrics",
    "EvolveResult",
    "PostmortemAnalyzer",
    "RegressionDetector",
    "RegressionReport",
    "RunRetrospective",
    "SkillCandidate",
    "SkillExtractor",
    "SkillPromotionPipeline",
]


def __getattr__(name: str) -> object:
    """Backward-compat shim for deprecated evolve module exports."""
    if name == "RunPostmortem":  # deprecated alias -- use RunRetrospective; removed in Wave 15
        import warnings

        warnings.warn(
            "hi_agent.evolve.RunPostmortem is deprecated; use RunRetrospective instead. "
            "RunPostmortem will be removed in Wave 15.",
            DeprecationWarning,
            stacklevel=2,
        )
        return RunRetrospective
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")