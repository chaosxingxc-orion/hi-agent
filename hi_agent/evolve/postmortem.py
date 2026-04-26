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
from hi_agent.failures.taxonomy import is_budget_exhausted_failure_code

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

        Rule-based heuristics always run.  When an LLM gateway is present,
        ``_llm_analyze()`` is called and its changes are merged in.

        Args:
            postmortem: Structured postmortem data for the run.

        Returns:
            An EvolveResult containing proposed changes and metrics.
        """
        changes = self._rule_based_analysis(postmortem)
        llm_calls = 0

        if self._llm is not None:
            try:
                llm_changes, llm_calls = self._llm_analyze(postmortem)
                # Deduplicate by (change_type, target_id): LLM wins on collision.
                existing_keys = {(c.change_type, c.target_id) for c in changes}
                for lc in llm_changes:
                    key = (lc.change_type, lc.target_id)
                    if key not in existing_keys:
                        changes.append(lc)
                        existing_keys.add(key)
                    else:
                        # Replace rule-based with LLM version when confidence is higher.
                        for i, c in enumerate(changes):
                            if (c.change_type, c.target_id) == key:
                                if lc.confidence > c.confidence:
                                    changes[i] = lc
                                break
            except Exception as exc:
                from hi_agent.observability.fallback import record_fallback

                record_fallback(
                    "heuristic",
                    reason="postmortem_llm_analyze_failed",
                    run_id=postmortem.run_id or "unknown",
                    extra={
                        "site": "PostmortemAnalyzer.analyze",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                    },
                )

        metrics = EvolveMetrics(
            runs_analyzed=1,
            llm_calls_used=llm_calls,
            skill_candidates_found=sum(1 for c in changes if c.change_type == "skill_candidate"),
            regressions_detected=sum(1 for c in changes if c.change_type == "baseline_update"),
        )

        # Determine change_scope from the changes produced.
        scope = _infer_scope(changes)

        return EvolveResult(
            trigger="per_run_postmortem",
            change_scope=scope,
            changes=changes,
            metrics=metrics,
            run_ids_analyzed=[postmortem.run_id],
            timestamp=datetime.datetime.now(tz=datetime.UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _llm_analyze(self, postmortem: RunPostmortem) -> tuple[list[EvolveChange], int]:
        """Use LLM to extract deeper improvement signals from the postmortem.

        Asks the LLM to:
        - Identify routing improvements not captured by rules
        - Suggest knowledge gaps to fill
        - Recommend skill candidates from the trajectory

        Returns:
            (list of EvolveChange, llm_call_count)
        """
        from hi_agent.llm.protocol import LLMRequest

        prompt = _build_postmortem_prompt(postmortem)
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            model="default",
            temperature=0.3,
            max_tokens=1024,
            metadata={"purpose": "evaluation", "run_id": postmortem.run_id},
        )
        response = self._llm.complete(request)  # type: ignore[union-attr]
        changes = _parse_llm_changes(response.content, postmortem.run_id)
        return changes, 1

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
        high_risk = {
            "unsafe_action_blocked",
            "model_refusal",
        }
        detected = high_risk & set(postmortem.failure_codes)
        budget_failure_codes = sorted(
            {code for code in postmortem.failure_codes if is_budget_exhausted_failure_code(code)}
        )
        if budget_failure_codes:
            detected.add("budget_exhausted")
        if detected:
            budget_note = (
                f" Budget codes observed: {budget_failure_codes}." if budget_failure_codes else ""
            )
            changes.append(
                EvolveChange(
                    change_type="routing_heuristic",
                    target_id=f"failure_codes:{','.join(sorted(detected))}",
                    description=(
                        f"High-risk failure codes detected: {sorted(detected)}."
                        f"{budget_note} Routing should add guards for these scenarios."
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


# ---------------------------------------------------------------------------
# LLM prompt helpers
# ---------------------------------------------------------------------------


def _build_postmortem_prompt(postmortem: RunPostmortem) -> str:
    """Build a structured prompt for LLM postmortem analysis."""
    lines = [
        "You are an AI agent improvement advisor. Analyze this run postmortem and "
        "suggest concrete improvements. Output a JSON array of change objects.",
        "",
        f"Run: {postmortem.run_id}  Task family: {postmortem.task_family}",
        f"Outcome: {postmortem.outcome}  Actions: {postmortem.total_actions}",
        f"Stages completed: {postmortem.stages_completed}",
        f"Stages failed: {postmortem.stages_failed}",
        f"Failure codes: {postmortem.failure_codes}",
        f"Branches explored: {postmortem.branches_explored}  Pruned: {postmortem.branches_pruned}",
        f"Quality score: {postmortem.quality_score}  "
        f"Efficiency score: {postmortem.efficiency_score}",
        f"Trajectory: {postmortem.trajectory_summary}",
        "",
        'Return a JSON array. Each item must have: "change_type" (one of '
        '"routing_heuristic", "skill_candidate", "knowledge_update", "baseline_update"), '
        '"target_id" (string), "description" (string), "confidence" (0.0-1.0).',
        "Return [] if no meaningful improvements are found.",
        "Output ONLY the JSON array, no surrounding text.",
    ]
    return "\n".join(lines)


def _parse_llm_changes(content: str, run_id: str) -> list[EvolveChange]:
    """Parse LLM JSON output into EvolveChange objects."""
    import json
    import logging

    _logger = logging.getLogger(__name__)
    content = content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        _logger.warning("postmortem._parse_llm_changes: invalid JSON from LLM: %s", exc)
        try:
            from hi_agent.observability.fallback import record_fallback

            record_fallback(
                "heuristic",
                reason="llm_json_parse_error",
                run_id=run_id or "unknown",
                extra={
                    "site": "postmortem._parse_llm_changes",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                    "content_preview": content[:200],
                },
            )
        except Exception:
            pass
        return []

    if not isinstance(raw, list):
        return []

    valid_types = {"routing_heuristic", "skill_candidate", "knowledge_update", "baseline_update"}
    changes: list[EvolveChange] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        change_type = str(item.get("change_type", ""))
        if change_type not in valid_types:
            continue
        target_id = str(item.get("target_id", "")).strip()
        description = str(item.get("description", "")).strip()
        if not target_id or not description:
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5
        changes.append(
            EvolveChange(
                change_type=change_type,
                target_id=target_id,
                description=description,
                confidence=confidence,
                evidence_refs=[run_id],
            )
        )
    return changes
