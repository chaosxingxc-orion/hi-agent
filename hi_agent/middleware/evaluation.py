"""Evaluation middleware: assess quality, decide pass/retry/escalate.

Receives ExecutionResult(s), assesses quality per node, decides:
  - pass: quality >= threshold, proceed
  - retry: quality below threshold but retries remain -> reflection -> execution
  - escalate: retries exhausted -> escalation -> control for re-planning
  - fail: terminal failure
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hi_agent.middleware.protocol import (
    EvaluationResult,
    MiddlewareMessage,
)

logger = logging.getLogger(__name__)


class EvaluationMiddleware:
    """Quality assessment and routing middleware."""

    def __init__(
        self,
        quality_threshold: float = 0.7,
        max_retries: int = 3,
        llm_gateway: Any | None = None,
        model_tier: str = "light",
        evaluator: Any | None = None,
    ) -> None:
        """Initialize EvaluationMiddleware.

        Args:
            quality_threshold: Score threshold for pass verdict.
            max_retries: Max retry attempts before escalation.
            llm_gateway: Optional LLM gateway for LLM-based scoring.
            model_tier: Model tier to use for LLM evaluation.
            evaluator: Optional pluggable Evaluator (satisfies the
                ``hi_agent.evaluation.contracts.Evaluator`` protocol).
                When provided, overrides both heuristic and LLM scoring.
                Use ``EvaluatorRuntime`` to wrap a custom evaluator alongside
                the platform DefaultEvaluator.
        """
        self._quality_threshold = quality_threshold
        self._max_retries = max_retries
        self._llm_gateway = llm_gateway
        self._model_tier = model_tier
        self._evaluator = evaluator  # pluggable; overrides heuristic/LLM scoring
        self._retry_counts: dict[str, int] = {}  # node_id -> count

    @property
    def name(self) -> str:
        """Return name."""
        return "evaluation"

    def on_create(self, config: dict[str, Any]) -> None:
        """Configure from external config dict."""
        if "quality_threshold" in config:
            self._quality_threshold = config["quality_threshold"]
        if "max_retries" in config:
            self._max_retries = config["max_retries"]

    def on_destroy(self) -> None:
        """Cleanup resources."""
        self._retry_counts.clear()
        self._llm_gateway = None

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage:
        """Evaluate execution results and decide next action."""
        run_id: str | None = message.metadata.get("run_id")
        payload = message.payload
        results = payload.get("results", [])
        perception_text = payload.get("perception_text", "")

        evaluations: list[dict[str, Any]] = []
        overall_verdict = "pass"
        overall_score = 1.0

        for result in results:
            node_id = result.get("node_id", "unknown")
            success = result.get("success", True)
            output = result.get("output")
            error = result.get("error")

            # Detect synthetic output from ExecutionMiddleware
            is_synthetic = isinstance(output, dict) and output.get("_synthetic") is True

            if not success:
                score = 0.0
                scoring_mode = "heuristic"
                evaluator_meta: dict = {"evaluator_id": "heuristic", "fallback_reason": ""}
            elif is_synthetic:
                score = 0.0
                scoring_mode = "heuristic"
                evaluator_meta = {"evaluator_id": "heuristic", "fallback_reason": ""}
            else:
                score, scoring_mode, evaluator_meta = self._assess_quality(
                    node_id=node_id,
                    output=output,
                    evidence=result.get("evidence", []),
                    task_goal=perception_text,
                    run_id=run_id,
                )

            issues: list[str] = []
            if is_synthetic:
                issues.append("synthetic_output")

            retry_count = self._retry_counts.get(node_id, 0)
            feedback = self._generate_feedback(node_id, score, output, error)

            if score >= self._quality_threshold:
                verdict = "pass"
            elif self._should_escalate(node_id, retry_count):
                verdict = "escalate"
                overall_verdict = "escalate"
            else:
                verdict = "retry"
                self._retry_counts[node_id] = retry_count + 1
                if overall_verdict == "pass":
                    overall_verdict = "retry"

            eval_result = EvaluationResult(
                node_id=node_id,
                verdict=verdict,
                quality_score=score,
                feedback=feedback,
                retry_instruction=(
                    self._make_retry_instruction(feedback) if verdict == "retry" else None
                ),
                retry_count=retry_count,
                max_retries=self._max_retries,
            )

            evaluations.append(
                {
                    "node_id": eval_result.node_id,
                    "verdict": eval_result.verdict,
                    "quality_score": eval_result.quality_score,
                    "feedback": eval_result.feedback,
                    "retry_instruction": eval_result.retry_instruction,
                    "retry_count": eval_result.retry_count,
                    "max_retries": eval_result.max_retries,
                    "issues": issues,
                    "scoring_mode": scoring_mode,
                    "evaluator_id": evaluator_meta.get("evaluator_id", "heuristic"),
                    "fallback_reason": evaluator_meta.get("fallback_reason", ""),
                }
            )

            overall_score = min(overall_score, score)

        # Determine target based on overall verdict
        if overall_verdict == "escalate":
            target = "control"
            msg_type = "escalation"
        elif overall_verdict == "retry":
            target = "execution"
            msg_type = "reflection"
        else:
            target = "end"
            msg_type = "evaluation_result"

        return MiddlewareMessage(
            source="evaluation",
            target=target,
            msg_type=msg_type,
            payload={
                "evaluations": evaluations,
                "overall_verdict": overall_verdict,
                "overall_score": overall_score,
                "perception_text": perception_text,
            },
            token_cost=message.token_cost,
            metadata=message.metadata,
        )

    def _assess_quality(
        self,
        node_id: str,
        output: Any,
        evidence: list[str],
        task_goal: str = "",
        run_id: str | None = None,
    ) -> tuple[float, str, dict]:
        """Assess quality of execution output.

        Returns:
            Tuple of (score 0.0-1.0, scoring_mode, evaluator_meta).
            evaluator_meta contains:
              - evaluator_id: class name of the evaluator used, or "heuristic"
              - fallback_reason: why fallback happened, or empty string
        """
        if output is None:
            return 0.0, "heuristic", {"evaluator_id": "heuristic", "fallback_reason": ""}

        # Pluggable evaluator takes highest priority.
        if self._evaluator is not None:
            try:
                from hi_agent.evaluation.contracts import EvaluationContext

                output_dict = (
                    output if isinstance(output, dict) else {"output": output, "evidence": evidence}
                )
                ctx = EvaluationContext(
                    goal=task_goal,
                    stage_id=node_id,
                    evidence=[{"raw": e} for e in evidence] if evidence else [],
                )
                result = self._evaluator.evaluate(ctx, output_dict)
                evaluator_meta = {
                    "evaluator_id": type(self._evaluator).__name__,
                    "fallback_reason": "",
                }
                return result.score, "evaluator", evaluator_meta
            except Exception as exc:
                logger.warning(
                    "Pluggable evaluator failed for node '%s', falling back to heuristic scoring",
                    node_id,
                    exc_info=True,
                )
                fallback_meta = {
                    "evaluator_id": type(self._evaluator).__name__,
                    "fallback_reason": str(exc),
                }
                return (
                    self._heuristic_score(output, evidence),
                    "heuristic",
                    fallback_meta,
                )

        # Try LLM-based scoring when gateway is available
        if self._llm_gateway is not None:
            try:
                score, _issues = self._llm_evaluate(task_goal, str(output), run_id=run_id)
                return score, "llm", {"evaluator_id": "llm", "fallback_reason": ""}
            except Exception as exc:
                from hi_agent.observability.fallback import record_fallback

                record_fallback(
                    "heuristic",
                    reason="llm_evaluator_failed_heuristic_score",
                    run_id=run_id or "unknown",
                    extra={
                        "site": "EvaluationMiddleware._assess_quality",
                        "node_id": node_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                    },
                    logger=logger,
                )

        return (
            self._heuristic_score(output, evidence),
            "heuristic",
            {"evaluator_id": "heuristic", "fallback_reason": ""},
        )

    def _heuristic_score(self, output: Any, evidence: list[str]) -> float:
        """Heuristic quality scoring. Returns 0.0-1.0."""
        score = 0.5  # base score for having output

        # Check output substance
        output_str = str(output)
        if len(output_str) > 10:
            score += 0.2
        if len(output_str) > 50:
            score += 0.1

        # Evidence contributes to quality
        if evidence:
            score += min(0.2, len(evidence) * 0.1)

        return min(1.0, score)

    def _llm_evaluate(
        self,
        task_goal: str,
        output: str,
        *,
        run_id: str | None = None,
    ) -> tuple[float, list[str]]:
        """Use LLM to evaluate output quality.

        Args:
            task_goal: The task objective to evaluate against.
            output: The execution output to assess.
            run_id: Optional run identifier threaded into request metadata.

        Returns:
            Tuple of (score 0.0-1.0, list of issues).

        Raises:
            Exception: On any LLM or parsing failure.
        """
        from hi_agent.llm.protocol import LLMRequest

        prompt = (
            "Rate the quality of this output (0.0-1.0) for the given task. "
            'Return JSON: {"score": float, "issues": [str], '
            '"strengths": [str]}\n\n'
            f"Task: {task_goal}\n\n"
            f"Output: {output}"
        )
        request = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=512,
            metadata={"purpose": self._model_tier, "run_id": run_id},
        )
        response = self._llm_gateway.complete(request)  # type: ignore[union-attr]  expiry_wave: Wave 28
        parsed = json.loads(response.content)

        raw_score = float(parsed["score"])
        # Clamp to valid range
        score = max(0.0, min(1.0, raw_score))
        issues = list(parsed.get("issues", []))
        return score, issues

    def _generate_feedback(
        self,
        node_id: str,
        score: float,
        output: Any,
        error: str | None,
    ) -> str:
        """Generate human-readable feedback."""
        if error:
            return f"Node '{node_id}' failed: {error}"
        if score >= self._quality_threshold:
            return f"Node '{node_id}' passed (score={score:.2f})"
        return (
            f"Node '{node_id}' below threshold "
            f"(score={score:.2f}, threshold={self._quality_threshold})"
        )

    def _should_escalate(self, node_id: str, retry_count: int) -> bool:
        """Determine if a node should escalate (retries exhausted)."""
        return retry_count >= self._max_retries

    def _make_retry_instruction(self, feedback: str) -> str:
        """Create instruction for retry based on feedback."""
        return f"Please improve: {feedback}"
