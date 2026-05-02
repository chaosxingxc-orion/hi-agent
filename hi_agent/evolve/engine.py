"""Main Evolve engine orchestrator."""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import TYPE_CHECKING

from hi_agent.evolve.champion_challenger import ChampionChallenger
from hi_agent.evolve.contracts import (
    EvolutionTrial,
    EvolveChange,
    EvolveMetrics,
    EvolveResult,
    ProjectRetrospective,
    RunRetrospective,
)
from hi_agent.evolve.experiment_store import ExperimentStore, InMemoryExperimentStore
from hi_agent.evolve.regression_detector import RegressionDetector, RegressionReport
from hi_agent.evolve.retrospective import PostmortemAnalyzer
from hi_agent.evolve.skill_extractor import SkillCandidate, SkillExtractor

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway
    from hi_agent.skill.registry import SkillRegistry
    from hi_agent.skill.version import SkillVersionManager

_logger = logging.getLogger(__name__)

_DEFAULT_COMPARISON_INTERVAL = 10


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
        version_manager: SkillVersionManager | None = None,
        comparison_interval: int = _DEFAULT_COMPARISON_INTERVAL,
        experiment_store: ExperimentStore | None = None,
    ) -> None:
        """Initialize the evolve engine.

        Args:
            llm_gateway: Optional LLM gateway for deeper analysis.
            skill_extractor: Skill extractor instance; required (Rule 6).
            regression_detector: Regression detector; required (Rule 6).
            champion_challenger: Champion/challenger comparator; required (Rule 6).
            skill_registry: Optional skill registry for auto-registering candidates.
            version_manager: Optional skill version manager for auto-promote.
            comparison_interval: Number of runs between champion/challenger comparisons.
<<<<<<< HEAD
            experiment_store: Store for EvolutionTrial records; defaults to
                InMemoryExperimentStore for backwards-compat with existing callers.
        """
        self._llm = llm_gateway
        self._postmortem_analyzer = PostmortemAnalyzer(llm_gateway=llm_gateway)
        if skill_extractor is None:
            raise ValueError(
                "EvolveEngine.skill_extractor must be injected by the builder 鈥?"
                "unscoped SkillExtractor is not permitted (Rule 6). "
                "Pass skill_extractor=SkillExtractor() explicitly."
            )
        self._skill_extractor = skill_extractor
        if regression_detector is None:
            raise ValueError(
                "EvolveEngine.regression_detector must be injected by the builder 鈥?"
                "unscoped RegressionDetector is not permitted (Rule 6). "
                "Pass regression_detector=RegressionDetector() explicitly."
            )
        self._regression_detector = regression_detector
        if champion_challenger is None:
            raise ValueError(
                "EvolveEngine.champion_challenger must be injected by the builder 鈥?"
                "unscoped ChampionChallenger is not permitted (Rule 6). "
                "Pass champion_challenger=ChampionChallenger() explicitly."
            )
        self._champion_challenger = champion_challenger
        self._skill_registry = skill_registry
        self._version_manager = version_manager
        self._comparison_interval = comparison_interval
        self._skill_candidates: list[SkillCandidate] = []
        self._experiment_store: ExperimentStore = (
            experiment_store if experiment_store is not None else InMemoryExperimentStore()
        )

    def on_run_completed(self, postmortem: RunRetrospective) -> EvolveResult:
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
                    try:
                        self._skill_registry.register_candidate(candidate)
                    except Exception as _reg_exc:
                        _logger.warning(
                            "EvolveEngine: failed to register skill candidate %r: %s",
                            candidate.skill_id,
                            _reg_exc,
                            exc_info=True,
                        )

        # 3. Record metrics for regression detection.
        if postmortem.quality_score is not None and postmortem.efficiency_score is not None:
            self._regression_detector.record(
                run_id=postmortem.run_id,
                task_family=postmortem.task_family,
                quality=postmortem.quality_score,
                efficiency=postmortem.efficiency_score,
            )

        # 4. Champion/challenger: record metrics for skills used in this run.
        try:
            self._record_skill_metrics(postmortem, result)
        except Exception:
            _logger.debug(
                "champion_challenger recording failed for run %s",
                postmortem.run_id,
                exc_info=True,
            )

        return result

    # ------------------------------------------------------------------
    # Champion/Challenger helpers
    # ------------------------------------------------------------------

    def _record_skill_metrics(self, postmortem: RunRetrospective, result: EvolveResult) -> None:
        """Record skill metrics and trigger comparisons when due."""
        cc = self._champion_challenger
        vm = self._version_manager
        skills_used = postmortem.skills_used
        if not skills_used:
            return

        # Build run-level metrics from postmortem scores.
        run_metrics: dict[str, float] = {}
        if postmortem.quality_score is not None:
            run_metrics["quality"] = postmortem.quality_score
        if postmortem.efficiency_score is not None:
            run_metrics["efficiency"] = postmortem.efficiency_score
        if not run_metrics:
            return

        for skill_id in skills_used:
            # Determine if this skill has a challenger via version_manager.
            is_challenger = False
            version = "unknown"
            if vm is not None:
                challenger = vm.get_challenger(skill_id)
                champion = vm.get_champion(skill_id)
                if challenger is not None:
                    is_challenger = True
                    version = challenger.version
                elif champion is not None:
                    version = champion.version

            cc.record(
                scope=skill_id,
                version=version,
                metrics=run_metrics,
                is_challenger=is_challenger,
            )

        # Check if any scopes are due for comparison.
        for scope in cc.scopes_with_challenger():
            if cc.get_run_count(scope) % self._comparison_interval != 0:
                continue
            comparison = cc.compare(scope)
            if comparison.recommendation == "promote_challenger":
                _logger.info(
                    "Champion/challenger comparison for '%s': promoting "
                    "challenger %s (score=%.3f) over champion %s (score=%.3f)",
                    scope,
                    comparison.challenger_version,
                    comparison.challenger_score,
                    comparison.champion_version,
                    comparison.champion_score,
                )
                result.changes.append(
                    EvolveChange(
                        change_type="champion_challenger_promotion",
                        target_id=scope,
                        description=(
                            f"Challenger {comparison.challenger_version} "
                            f"outperforms champion {comparison.champion_version} "
                            f"({comparison.challenger_score:.3f} vs "
                            f"{comparison.champion_score:.3f})"
                        ),
                        confidence=min(comparison.challenger_score, 1.0),
                        evidence_refs=[postmortem.run_id],
                    )
                )
                # Record the promotion as an EvolutionTrial.
                try:
                    exp = EvolutionTrial(
                        experiment_id=str(uuid.uuid4()),
                        capability_name=scope,
                        baseline_version=comparison.champion_version,
                        candidate_version=comparison.challenger_version,
                        metric_name="champion_challenger_score",
                        started_at=datetime.datetime.now(tz=datetime.UTC).isoformat(),
                        status="active",
                        tenant_id=getattr(postmortem, "tenant_id", ""),
                        project_id=getattr(postmortem, "project_id", ""),
                        run_id=postmortem.run_id,
                    )
                    self._experiment_store.start_experiment(exp)
                except Exception:
                    _logger.debug(
                        "experiment_store.start_experiment failed for scope '%s'",
                        scope,
                        exc_info=True,
                    )
                # Auto-promote via version_manager if available.
                if vm is not None:
                    try:
                        vm.promote_challenger(scope)
                        _logger.info("Auto-promoted challenger for skill '%s'", scope)
                        try:
                            vm.save()
                        except Exception:
                            _logger.debug(
                                "SkillVersionManager.save failed after promote '%s'",
                                scope,
                                exc_info=True,
                            )
                    except Exception:
                        _logger.debug(
                            "Auto-promote failed for '%s'",
                            scope,
                            exc_info=True,
                        )

    def on_project_completed(self, project_id: str, run_ids: list[str]) -> ProjectRetrospective:
        """Aggregate postmortems for all runs of a project into one ProjectRetrospective.

        Args:
            project_id: The project identifier.
            run_ids: All run IDs that belong to this project.

        Returns:
            A ProjectRetrospective with the given project_id and run_ids.
            Aggregation is record-only in Wave 8; richer cross-run analysis
            is deferred to Wave 9 (Phase B).
        """
        backtrack_count = 0
        accepted_artifacts: list[str] = []
        rejected_artifacts: list[str] = []
        skill_deltas: list[str] = []

        for run_id in run_ids:
            try:
                postmortem_record = getattr(self._postmortem_analyzer, "get_postmortem", None)
                if postmortem_record is not None:
                    pm = postmortem_record(run_id)
                    if pm is not None:
                        backtrack_count += pm.branches_pruned
            except Exception:
                _logger.debug(
                    "on_project_completed: skipping run_id=%s (no stored postmortem)",
                    run_id,
                )

        return ProjectRetrospective(
            project_id=project_id,
            run_ids=list(run_ids),
            backtrack_count=backtrack_count,
            accepted_artifact_ids=accepted_artifacts,
            rejected_artifact_ids=rejected_artifacts,
            skill_deltas=skill_deltas,
        )

    def batch_evolve(
        self,
        postmortems: list[RunRetrospective],
        change_scope: str,
        route_engine: object | None = None,
    ) -> EvolveResult:
        """Trigger batch evolution across multiple runs.

        Analyzes multiple runs together and produces changes restricted to
        a single change scope.  When *route_engine* is provided and the scope
        produces routing changes, they are applied immediately via
        ``route_engine.apply_evolve_changes()``.

        Args:
            postmortems: List of postmortem data for runs to analyze.
            change_scope: The scope to restrict changes to.
            route_engine: Optional route engine to apply routing changes inline.

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

        evolve_result = EvolveResult(
            trigger="batch_evolution",
            change_scope=change_scope,
            changes=all_changes,
            metrics=total_metrics,
            run_ids_analyzed=run_ids,
            timestamp=datetime.datetime.now(tz=datetime.UTC).isoformat(),
        )

        # Inline policy application: apply routing changes to route engine immediately.
        if route_engine is not None and all_changes:
            routing_changes = [
                c
                for c in all_changes
                if c.change_type
                in ("routing_heuristic", "efficiency_heuristic", "route_config_updated")
            ]
            if routing_changes:
                try:
                    route_engine.apply_evolve_changes(routing_changes)  # type: ignore[union-attr]  expiry_wave: permanent
                    _logger.info(
                        "batch_evolve.route_changes_applied scope=%s count=%d",
                        change_scope,
                        len(routing_changes),
                    )
                except Exception as exc:
                    _logger.warning(
                        "batch_evolve.route_changes_failed scope=%s error=%s",
                        change_scope,
                        exc,
                    )

        return evolve_result

    def check_regression(self, task_family: str) -> RegressionReport:
        """Check for regressions in a task family.

        Args:
            task_family: The task family to check.

        Returns:
            A RegressionReport with findings.
        """
        return self._regression_detector.check(task_family)

