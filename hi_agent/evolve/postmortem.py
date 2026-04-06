"""Per-run postmortem analysis for the Evolve subsystem."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from hi_agent.evolve.contracts import (
    EvolveChange,
    EvolveMetrics,
    EvolveResult,
    RunPostmortem,
)

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway


class PostmortemAnalyzer:
    """Analyzes a completed run to extract improvement signals.

    This is the primary evolve trigger -- runs after every task completion.
    Without an LLM gateway, uses rule-based heuristics only.  With an LLM
    gateway, additionally extracts skill candidates and routing improvements.
    """

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        """Initialize the postmortem analyzer.

        Args:
            llm_gateway: Optional LLM gateway for deeper analysis.
        """
        self._llm = llm_gateway

    def analyze(self, postmortem: RunPostmortem) -> EvolveResult:
        """Run postmortem analysis on a completed run.

        Args:
            postmortem: Structured postmortem data for the run.

        Returns:
            An EvolveResult containing proposed changes and metrics.
        """
        changes = self._rule_based_analysis(postmortem)
        metrics = EvolveMetrics(
            runs_analyzed=1,
            skill_candidates_found=sum(
                1 for c in changes if c.change_type == "skill_candidate"
            ),
            regressions_detected=sum(
                1 for c in changes if c.change_type == "baseline_update"
            ),
        )

        # Determine change_scope from the changes produced.
        scope = _infer_scope(changes)

        return EvolveResult(
            trigger="per_run_postmortem",
            change_scope=scope,
            changes=changes,
            metrics=metrics,
            run_ids_analyzed=[postmortem.run_id],
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rule_based_analysis(self, postmortem: RunPostmortem) -> list[EvolveChange]:
        """Apply rule-based heuristics to extract improvement signals.

        Args:
            postmortem: Structured postmortem data.

        Returns:
            List of proposed changes.
        """
        changes: list[EvolveChange] = []
        changes.extend(self._detect_failure_patterns(postmortem))
        changes.extend(self._assess_branch_efficiency(postmortem))
        return changes

    def _detect_failure_patterns(self, postmortem: RunPostmortem) -> list[EvolveChange]:
        """Detect recurring failure patterns.

        Args:
            postmortem: Structured postmortem data.

        Returns:
            List of routing heuristic changes for detected failure patterns.
        """
        changes: list[EvolveChange] = []

        # High failure-code density suggests routing should avoid certain paths.
        if len(postmortem.failure_codes) >= 3:
            changes.append(
                EvolveChange(
                    change_type="routing_heuristic",
                    target_id=f"task_family:{postmortem.task_family}",
                    description=(
                        f"High failure density ({len(postmortem.failure_codes)} codes) "
                        f"in task family '{postmortem.task_family}'. "
                        f"Consider adjusting routing to avoid known-bad paths."
                    ),
                    confidence=min(0.5 + 0.1 * len(postmortem.failure_codes), 0.95),
                    evidence_refs=[postmortem.run_id],
                )
            )

        # Specific high-risk failure codes.
        high_risk = {"unsafe_action_blocked", "budget_exhausted", "model_refusal"}
        detected = high_risk & set(postmortem.failure_codes)
        if detected:
            changes.append(
                EvolveChange(
                    change_type="routing_heuristic",
                    target_id=f"failure_codes:{','.join(sorted(detected))}",
                    description=(
                        f"High-risk failure codes detected: {sorted(detected)}. "
                        f"Routing should add guards for these scenarios."
                    ),
                    confidence=0.8,
                    evidence_refs=[postmortem.run_id],
                )
            )

        return changes

    def _assess_branch_efficiency(self, postmortem: RunPostmortem) -> list[EvolveChange]:
        """Assess whether branch exploration was efficient.

        Args:
            postmortem: Structured postmortem data.

        Returns:
            List of routing heuristic changes for inefficient exploration.
        """
        changes: list[EvolveChange] = []

        if postmortem.branches_explored == 0:
            return changes

        prune_ratio = postmortem.branches_pruned / postmortem.branches_explored
        if prune_ratio > 0.5 and postmortem.branches_explored >= 3:
            changes.append(
                EvolveChange(
                    change_type="routing_heuristic",
                    target_id=f"branch_efficiency:{postmortem.task_family}",
                    description=(
                        f"High prune ratio ({prune_ratio:.0%}) with "
                        f"{postmortem.branches_explored} branches explored. "
                        f"Route engine may benefit from tighter pre-filtering."
                    ),
                    confidence=min(0.4 + prune_ratio * 0.4, 0.85),
                    evidence_refs=[postmortem.run_id],
                )
            )

        return changes


def _infer_scope(changes: list[EvolveChange]) -> str:
    """Infer the change scope from the types of changes produced.

    Args:
        changes: The list of proposed changes.

    Returns:
        A change scope string.
    """
    if not changes:
        return "routing_only"

    type_to_scope = {
        "routing_heuristic": "routing_only",
        "skill_candidate": "skill_candidates_only",
        "knowledge_update": "knowledge_summaries_only",
        "baseline_update": "evaluation_baselines_only",
    }

    scopes = {type_to_scope.get(c.change_type, "routing_only") for c in changes}
    if len(scopes) == 1:
        return scopes.pop()
    # When multiple scopes are present, use the first change's scope
    # to enforce single-scope isolation.
    return type_to_scope.get(changes[0].change_type, "routing_only")
