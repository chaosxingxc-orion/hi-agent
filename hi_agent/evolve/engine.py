"""Main Evolve engine orchestrator."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import (
    EvolveChange,
    EvolveMetrics,
    EvolveResult,
    RunPostmortem,
)
from hi_agent.evolve.postmortem import PostmortemAnalyzer
from hi_agent.evolve.regression_detector import RegressionDetector, RegressionReport
from hi_agent.evolve.skill_extractor import SkillCandidate, SkillExtractor

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway
    from hi_agent.skill.registry import SkillRegistry


class EvolveEngine:
    """Orchestrates the full Evolve lifecycle.

    Coordinates postmortem analysis, skill extraction, regression detection,
    and champion/challenger comparison into a unified evolution pipeline.
    """

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        skill_extractor: SkillExtractor | None = None,
        regression_detector: RegressionDetector | None = None,
        champion_challenger: ChampionChallenger | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        """Initialize the evolve engine.

        Args:
            llm_gateway: Optional LLM gateway for deeper analysis.
            skill_extractor: Skill extractor instance; created if not provided.
            regression_detector: Regression detector; created if not provided.
            champion_challenger: Champion/challenger comparator; created if not provided.
            skill_registry: Optional skill registry for auto-registering candidates.
        """
        self._llm = llm_gateway
        self._postmortem_analyzer = PostmortemAnalyzer(llm_gateway=llm_gateway)
        self._skill_extractor = skill_extractor or SkillExtractor()
        self._regression_detector = regression_detector or RegressionDetector()
        self._champion_challenger = champion_challenger or ChampionChallenger()
        self._skill_registry = skill_registry
        self._skill_candidates: list[SkillCandidate] = []

    def on_run_completed(self, postmortem: RunPostmortem) -> EvolveResult:
        """Trigger per-run postmortem evolve.

        This is the main entry point, called after every task completion.
        It runs postmortem analysis, extracts skill candidates, and records
        metrics for regression detection.

        Args:
            postmortem: Structured postmortem data for the completed run.

        Returns:
            An EvolveResult with proposed changes.
        """
        # 1. Postmortem analysis (rule-based, optionally LLM-enhanced).
        result = self._postmortem_analyzer.analyze(postmortem)

        # 2. Skill extraction (only from successful runs).
        new_skills = self._skill_extractor.extract(postmortem)
        if new_skills:
            self._skill_candidates = self._skill_extractor.merge_candidates(
                self._skill_candidates, new_skills
            )
            for skill in new_skills:
                result.changes.append(
                    EvolveChange(
                        change_type="skill_candidate",
                        target_id=skill.skill_id,
                        description=skill.description,
                        confidence=skill.confidence,
                        evidence_refs=list(skill.source_run_ids),
                    )
                )
            result.metrics.skill_candidates_found += len(new_skills)

            # Auto-register candidates in the skill registry if available.
            if self._skill_registry is not None:
                for candidate in new_skills:
                    self._skill_registry.register_candidate(candidate)

        # 3. Record metrics for regression detection.
        if postmortem.quality_score is not None and postmortem.efficiency_score is not None:
            self._regression_detector.record(
                run_id=postmortem.run_id,
                task_family=postmortem.task_family,
                quality=postmortem.quality_score,
                efficiency=postmortem.efficiency_score,
            )

        return result

    def batch_evolve(
        self,
        postmortems: list[RunPostmortem],
        change_scope: str,
    ) -> EvolveResult:
        """Trigger batch evolution across multiple runs.

        Analyzes multiple runs together and produces changes restricted to
        a single change scope.

        Args:
            postmortems: List of postmortem data for runs to analyze.
            change_scope: The scope to restrict changes to.

        Returns:
            An EvolveResult with aggregated changes for the given scope.
        """
        all_changes: list[EvolveChange] = []
        total_metrics = EvolveMetrics(runs_analyzed=len(postmortems))
        run_ids: list[str] = []

        scope_to_type = {
            "routing_only": "routing_heuristic",
            "skill_candidates_only": "skill_candidate",
            "knowledge_summaries_only": "knowledge_update",
            "evaluation_baselines_only": "baseline_update",
        }
        allowed_type = scope_to_type.get(change_scope)

        for pm in postmortems:
            run_ids.append(pm.run_id)
            result = self._postmortem_analyzer.analyze(pm)

            # Also extract skills.
            new_skills = self._skill_extractor.extract(pm)
            for skill in new_skills:
                result.changes.append(
                    EvolveChange(
                        change_type="skill_candidate",
                        target_id=skill.skill_id,
                        description=skill.description,
                        confidence=skill.confidence,
                        evidence_refs=list(skill.source_run_ids),
                    )
                )

            # Filter to allowed scope.
            for change in result.changes:
                if allowed_type is None or change.change_type == allowed_type:
                    all_changes.append(change)

            total_metrics.skill_candidates_found += result.metrics.skill_candidates_found

        return EvolveResult(
            trigger="batch_evolution",
            change_scope=change_scope,
            changes=all_changes,
            metrics=total_metrics,
            run_ids_analyzed=run_ids,
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        )

    def check_regression(self, task_family: str) -> RegressionReport:
        """Check for regressions in a task family.

        Args:
            task_family: The task family to check.

        Returns:
            A RegressionReport with findings.
        """
        return self._regression_detector.check(task_family)
