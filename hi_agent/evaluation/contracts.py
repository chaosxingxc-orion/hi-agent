"""Evaluator plugin contracts for quality assessment.

The platform defines a generic Evaluator Protocol.  Business agents inject
their own evaluators via ProfileSpec.evaluator_factory — domain-specific
quality rules (citation completeness, source coverage, etc.) live in the
business layer, not here.

The DefaultEvaluator provides a generic baseline that any agent can use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass
class EvaluationContext:
    """Context passed to an evaluator describing the task and collected evidence."""

    goal: str
    stage_id: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Result produced by an evaluator."""

    score: float  # 0.0-1.0
    passed: bool
    criteria_results: dict[str, bool] = field(default_factory=dict)
    feedback: str = ""
    suggestions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Evaluator protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Evaluator(Protocol):
    """Protocol that all evaluators must satisfy.

    Business agents implement this to inject domain-specific evaluation
    rules without modifying the platform core.
    """

    def evaluate(
        self, context: EvaluationContext, output: dict[str, Any]
    ) -> EvaluationResult: ...


# ---------------------------------------------------------------------------
# Default platform evaluator (generic, domain-agnostic)
# ---------------------------------------------------------------------------

class DefaultEvaluator:
    """Generic platform evaluator for baseline quality assessment.

    Checks output structure without any domain-specific assumptions.
    Each criterion contributes equally (0.2 each) to the final score.

    Business agents that need stricter or domain-specific evaluation
    should implement a custom Evaluator via their ProfileSpec.
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold

    def evaluate(
        self, context: EvaluationContext, output: dict[str, Any]
    ) -> EvaluationResult:
        criteria: dict[str, bool] = {}

        # C1: output is non-empty
        criteria["non_empty"] = bool(output)

        # C2: output contains a primary content key
        criteria["has_output_key"] = any(
            k in output for k in ("output", "result", "content", "data")
        )

        # C3: output includes evidence or source references
        # "citations" is deprecated (Wave 14 removal); callers should use "evidence_refs".
        if "citations" in output and "evidence_refs" not in output:
            import warnings

            warnings.warn(
                "Output key 'citations' is deprecated and will stop being recognised in Wave 14. "
                "Use 'evidence_refs' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        criteria["has_evidence"] = any(
            k in output
            for k in ("evidence", "source_refs", "sources", "evidence_refs", "citations")
        )

        # C4: output has a meaningful score (>0.4) if one is present
        if "score" in output:
            try:
                criteria["score_meaningful"] = float(output["score"]) >= 0.4
            except (TypeError, ValueError):
                criteria["score_meaningful"] = False
        else:
            criteria["score_meaningful"] = True  # no score requirement if not present

        # C5: no explicit error indicators
        criteria["no_error"] = not (
            output.get("error")
            or output.get("success") is False
            or output.get("failed")
        )

        score = sum(criteria.values()) / len(criteria)
        passed = score >= self._threshold

        feedback_parts = [
            f"{k}: {'✓' if v else '✗'}" for k, v in criteria.items()
        ]
        feedback = f"score={score:.2f} [{', '.join(feedback_parts)}]"

        suggestions = []
        if not criteria["has_output_key"]:
            suggestions.append("Include an 'output' or 'result' key in the response")
        if not criteria["has_evidence"]:
            suggestions.append("Include 'evidence' or 'source_refs' for traceability")

        return EvaluationResult(
            score=score,
            passed=passed,
            criteria_results=criteria,
            feedback=feedback,
            suggestions=suggestions,
        )


# ---------------------------------------------------------------------------
# Composite evaluator (mix platform + business-layer evaluators)
# ---------------------------------------------------------------------------

class CompositeEvaluator:
    """Weighted combination of multiple evaluators.

    Usage::

        composite = CompositeEvaluator([
            (DefaultEvaluator(), 0.4),
            (my_business_evaluator, 0.6),
        ])
        result = composite.evaluate(context, output)

    The final score is the weighted average.
    ``passed`` is True only if ALL sub-evaluators pass.
    """

    def __init__(self, evaluators: list[tuple[Any, float]]) -> None:
        """Args:
        evaluators: List of (evaluator, weight) pairs.
            Weights need not sum to 1 — they are normalized internally.
        """
        if not evaluators:
            raise ValueError("CompositeEvaluator requires at least one evaluator")
        self._evaluators = evaluators

    def evaluate(
        self, context: EvaluationContext, output: dict[str, Any]
    ) -> EvaluationResult:
        results = [
            (ev.evaluate(context, output), weight)
            for ev, weight in self._evaluators
        ]
        total_weight = sum(w for _, w in results)
        if total_weight == 0:
            total_weight = 1.0

        weighted_score = sum(r.score * w for r, w in results) / total_weight
        all_passed = all(r.passed for r, _ in results)

        merged_criteria: dict[str, bool] = {}
        all_feedback: list[str] = []
        all_suggestions: list[str] = []
        for r, _ in results:
            merged_criteria.update(r.criteria_results)
            if r.feedback:
                all_feedback.append(r.feedback)
            all_suggestions.extend(r.suggestions)

        return EvaluationResult(
            score=weighted_score,
            passed=all_passed,
            criteria_results=merged_criteria,
            feedback=" | ".join(all_feedback),
            suggestions=all_suggestions,
        )
