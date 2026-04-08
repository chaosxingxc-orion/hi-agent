"""Evaluation middleware: assess quality, decide pass/retry/escalate.

Receives ExecutionResult(s), assesses quality per node, decides:
  - pass: quality >= threshold, proceed
  - retry: quality below threshold but retries remain -> reflection -> execution
  - escalate: retries exhausted -> escalation -> control for re-planning
  - fail: terminal failure
"""
from __future__ import annotations

from typing import Any

from hi_agent.middleware.protocol import (
    EvaluationResult,
    MiddlewareMessage,
)


class EvaluationMiddleware:
    """Quality assessment and routing middleware."""

    def __init__(
        self,
        quality_threshold: float = 0.7,
        max_retries: int = 3,
        llm_gateway: Any | None = None,
    ) -> None:
        self._quality_threshold = quality_threshold
        self._max_retries = max_retries
        self._llm_gateway = llm_gateway
        self._retry_counts: dict[str, int] = {}  # node_id -> count

    @property
    def name(self) -> str:
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

            if not success:
                score = 0.0
            else:
                score = self._assess_quality(
                    node_id=node_id,
                    output=output,
                    evidence=result.get("evidence", []),
                )

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
                retry_instruction=self._make_retry_instruction(feedback) if verdict == "retry" else None,
                retry_count=retry_count,
                max_retries=self._max_retries,
            )

            evaluations.append({
                "node_id": eval_result.node_id,
                "verdict": eval_result.verdict,
                "quality_score": eval_result.quality_score,
                "feedback": eval_result.feedback,
                "retry_instruction": eval_result.retry_instruction,
                "retry_count": eval_result.retry_count,
                "max_retries": eval_result.max_retries,
            })

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
        self, node_id: str, output: Any, evidence: list[str],
    ) -> float:
        """Assess quality of execution output. Returns 0.0-1.0."""
        if output is None:
            return 0.0

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

    def _generate_feedback(
        self, node_id: str, score: float, output: Any, error: str | None,
    ) -> str:
        """Generate human-readable feedback."""
        if error:
            return f"Node '{node_id}' failed: {error}"
        if score >= self._quality_threshold:
            return f"Node '{node_id}' passed (score={score:.2f})"
        return f"Node '{node_id}' below threshold (score={score:.2f}, threshold={self._quality_threshold})"

    def _should_escalate(self, node_id: str, retry_count: int) -> bool:
        """Determine if a node should escalate (retries exhausted)."""
        return retry_count >= self._max_retries

    def _make_retry_instruction(self, feedback: str) -> str:
        """Create instruction for retry based on feedback."""
        return f"Please improve: {feedback}"
