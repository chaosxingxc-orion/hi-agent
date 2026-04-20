"""Dataset evaluation pipeline for skill promotion decisions.

The ``DatasetEvaluator`` runs a batch of ``RunPostmortem`` records through
champion/challenger comparison and returns aggregate quality and efficiency
metrics.  ``SkillPromotionPipeline`` wraps it with automatic promotion logic.

Phase 2 — skill promotion and dataset evaluation pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from hi_agent.evolve.contracts import RunPostmortem

if TYPE_CHECKING:
    from hi_agent.evolve.champion_challenger import ChampionChallenger
    from hi_agent.skill.version import SkillVersionManager

_logger = logging.getLogger(__name__)


@dataclass
class SkillEvalSummary:
    """Aggregate evaluation summary for one skill across a dataset.

    Attributes:
        skill_id: Identifier for the skill evaluated.
        run_count: Number of postmortems that used this skill.
        avg_quality: Mean quality score across those runs.
        avg_efficiency: Mean efficiency score across those runs.
        champion_version: Champion version at evaluation time.
        challenger_version: Challenger version if one exists.
        recommendation: ``"promote"``, ``"keep"``, or ``"insufficient_data"``.
        confidence: Confidence in the recommendation (0.0–1.0).
    """

    skill_id: str
    run_count: int = 0
    avg_quality: float = 0.0
    avg_efficiency: float = 0.0
    champion_version: str = "unknown"
    challenger_version: str | None = None
    recommendation: str = "insufficient_data"
    confidence: float = 0.0


@dataclass
class DatasetEvalResult:
    """Result of a full dataset evaluation pass.

    Attributes:
        total_runs: Number of postmortems processed.
        skills_evaluated: Per-skill summaries keyed by skill_id.
        promotions_triggered: Skill IDs that were auto-promoted.
    """

    total_runs: int = 0
    skills_evaluated: dict[str, SkillEvalSummary] = field(default_factory=dict)
    promotions_triggered: list[str] = field(default_factory=list)


class DatasetEvaluator:
    """Batch dataset evaluation for champion/challenger skill comparison.

    Processes a list of ``RunPostmortem`` records, aggregates per-skill
    quality and efficiency metrics, and surfaces promotion recommendations.
    """

    # Minimum number of runs per skill before a recommendation is made.
    MIN_RUNS_FOR_RECOMMENDATION: int = 5
    # Minimum quality improvement for a promotion recommendation.
    PROMOTE_QUALITY_DELTA: float = 0.05

    def __init__(
        self,
        champion_challenger: ChampionChallenger | None = None,
        version_manager: SkillVersionManager | None = None,
    ) -> None:
        """Initialise the evaluator.

        Args:
            champion_challenger: Optional ChampionChallenger for recording metrics.
            version_manager: Optional SkillVersionManager for version lookups.
        """
        self._cc = champion_challenger
        self._vm = version_manager

    def evaluate(self, postmortems: list[RunPostmortem]) -> DatasetEvalResult:
        """Run evaluation over a dataset of postmortems.

        Args:
            postmortems: List of completed run postmortems.

        Returns:
            A :class:`DatasetEvalResult` with per-skill summaries.
        """
        result = DatasetEvalResult(total_runs=len(postmortems))

        # Aggregate raw scores per skill
        quality_sums: dict[str, list[float]] = {}
        efficiency_sums: dict[str, list[float]] = {}

        for pm in postmortems:
            for skill_id in pm.skills_used:
                q = pm.quality_score
                e = pm.efficiency_score
                if q is not None:
                    quality_sums.setdefault(skill_id, []).append(q)
                if e is not None:
                    efficiency_sums.setdefault(skill_id, []).append(e)

                # Also feed the champion/challenger tracker
                if self._cc is not None:
                    metrics: dict[str, float] = {}
                    if q is not None:
                        metrics["quality"] = q
                    if e is not None:
                        metrics["efficiency"] = e
                    if metrics:
                        version = "unknown"
                        is_challenger = False
                        if self._vm is not None:
                            challenger = self._vm.get_challenger(skill_id)
                            champion = self._vm.get_champion(skill_id)
                            if challenger is not None:
                                is_challenger = True
                                version = challenger.version
                            elif champion is not None:
                                version = champion.version
                        self._cc.record(
                            scope=skill_id,
                            version=version,
                            metrics=metrics,
                            is_challenger=is_challenger,
                        )

        # Build summaries and recommendations
        all_skills = set(quality_sums) | set(efficiency_sums)
        for skill_id in all_skills:
            qs = quality_sums.get(skill_id, [])
            es = efficiency_sums.get(skill_id, [])
            run_count = max(len(qs), len(es))
            avg_q = sum(qs) / len(qs) if qs else 0.0
            avg_e = sum(es) / len(es) if es else 0.0

            champion_version = "unknown"
            challenger_version = None
            if self._vm is not None:
                champ = self._vm.get_champion(skill_id)
                chal = self._vm.get_challenger(skill_id)
                if champ is not None:
                    champion_version = champ.version
                if chal is not None:
                    challenger_version = chal.version

            # Derive recommendation from champion/challenger comparison
            recommendation = "insufficient_data"
            confidence = 0.0

            if run_count >= self.MIN_RUNS_FOR_RECOMMENDATION and self._cc is not None:
                try:
                    comparison = self._cc.compare(skill_id)
                    if comparison.recommendation == "promote_challenger":
                        recommendation = "promote"
                        confidence = min(comparison.challenger_score, 1.0)
                    else:
                        recommendation = "keep"
                        confidence = 0.7
                except Exception:
                    recommendation = _simple_recommendation(avg_q, avg_e)
                    confidence = 0.5
            elif run_count >= self.MIN_RUNS_FOR_RECOMMENDATION:
                recommendation = _simple_recommendation(avg_q, avg_e)
                confidence = 0.5

            result.skills_evaluated[skill_id] = SkillEvalSummary(
                skill_id=skill_id,
                run_count=run_count,
                avg_quality=avg_q,
                avg_efficiency=avg_e,
                champion_version=champion_version,
                challenger_version=challenger_version,
                recommendation=recommendation,
                confidence=confidence,
            )

        return result


def _simple_recommendation(avg_quality: float, avg_efficiency: float) -> str:
    """Heuristic recommendation without champion/challenger data."""
    score = (avg_quality + avg_efficiency) / 2.0
    return "promote" if score >= 0.7 else "keep"


class SkillPromotionPipeline:
    """Combines dataset evaluation with automatic skill promotion.

    Usage::

        pipeline = SkillPromotionPipeline(
            evaluator=DatasetEvaluator(cc, vm),
            version_manager=vm,
            auto_promote=True,
        )
        report = pipeline.run(postmortems)
    """

    def __init__(
        self,
        evaluator: DatasetEvaluator,
        version_manager: SkillVersionManager | None = None,
        auto_promote: bool = False,
    ) -> None:
        """Initialise the pipeline.

        Args:
            evaluator: DatasetEvaluator for computing per-skill metrics.
            version_manager: SkillVersionManager for executing promotions.
            auto_promote: When True, automatically promote skills that receive
                a ``"promote"`` recommendation with confidence ≥ 0.7.
        """
        self._evaluator = evaluator
        self._vm = version_manager
        self._auto_promote = auto_promote

    def run(self, postmortems: list[RunPostmortem]) -> DatasetEvalResult:
        """Evaluate dataset and optionally auto-promote skills.

        Args:
            postmortems: List of run postmortems to evaluate.

        Returns:
            A :class:`DatasetEvalResult` with promotions_triggered populated.
        """
        result = self._evaluator.evaluate(postmortems)

        if not self._auto_promote or self._vm is None:
            return result

        for skill_id, summary in result.skills_evaluated.items():
            if summary.recommendation == "promote" and summary.confidence >= 0.7:
                try:
                    self._vm.promote_challenger(skill_id)
                    result.promotions_triggered.append(skill_id)
                    _logger.info(
                        "skill_promotion_pipeline.promoted skill_id=%s "
                        "confidence=%.2f avg_quality=%.2f avg_efficiency=%.2f",
                        skill_id,
                        summary.confidence,
                        summary.avg_quality,
                        summary.avg_efficiency,
                    )
                    try:
                        self._vm.save()
                    except Exception as exc:
                        _logger.debug(
                            "skill_promotion_pipeline.save_failed skill_id=%s error=%s",
                            skill_id,
                            exc,
                        )
                except Exception as exc:
                    _logger.warning(
                        "skill_promotion_pipeline.promote_failed skill_id=%s error=%s",
                        skill_id,
                        exc,
                    )

        return result
