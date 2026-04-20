"""Integration tests for evaluator injection into EvaluationMiddleware."""

from __future__ import annotations

from hi_agent.evaluation.contracts import (
    DefaultEvaluator,
    EvaluationResult,
)
from hi_agent.evaluation.runtime import EvaluatorRuntime
from hi_agent.middleware.evaluation import EvaluationMiddleware
from hi_agent.middleware.protocol import MiddlewareMessage


def _make_message(output: dict, score: float = 0.9, success: bool = True) -> MiddlewareMessage:
    return MiddlewareMessage(
        source="execution",
        target="evaluation",
        msg_type="execution_result",
        payload={
            "results": [
                {"node_id": "s1", "output": output, "success": success, "evidence": []},
            ],
            "perception_text": "test goal",
        },
    )


class TestEvaluatorRuntimeFactory:
    def test_no_evaluator_uses_default(self):
        runtime = EvaluatorRuntime(evaluator=None)
        assert isinstance(runtime.evaluator, DefaultEvaluator)

    def test_custom_evaluator_without_wrap(self):
        custom = DefaultEvaluator(threshold=0.9)
        runtime = EvaluatorRuntime(evaluator=custom, wrap_with_default=False)
        assert runtime.evaluator is custom

    def test_wrap_with_default_creates_composite(self):
        from hi_agent.evaluation.contracts import CompositeEvaluator

        custom = DefaultEvaluator(threshold=0.9)
        runtime = EvaluatorRuntime(evaluator=custom, wrap_with_default=True)
        assert isinstance(runtime.evaluator, CompositeEvaluator)

    def test_from_resolved_profile_no_evaluator(self):
        runtime = EvaluatorRuntime.from_resolved_profile(None)
        assert isinstance(runtime.evaluator, DefaultEvaluator)

    def test_from_resolved_profile_with_evaluator(self):
        from hi_agent.runtime.profile_runtime import ResolvedProfile

        class MyEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=1.0, passed=True)

        resolved = ResolvedProfile(
            profile_id="p1",
            evaluator=MyEval(),
        )
        runtime = EvaluatorRuntime.from_resolved_profile(resolved)
        assert runtime.evaluator is not None


class TestEvaluationMiddlewareWithEvaluator:
    def test_default_no_evaluator_heuristic(self):
        mw = EvaluationMiddleware(quality_threshold=0.5)
        msg = _make_message({"output": "some text"})
        result = mw.process(msg)
        assert result.payload["overall_verdict"] == "pass"
        eval_entry = result.payload["evaluations"][0]
        assert eval_entry["scoring_mode"] in ("heuristic", "evaluator")

    def test_injected_evaluator_is_used(self):
        """When an evaluator is injected, its score is used."""
        class HighScoreEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=1.0, passed=True)

        mw = EvaluationMiddleware(
            quality_threshold=0.5,
            evaluator=HighScoreEval(),
        )
        msg = _make_message({"output": "something"})
        result = mw.process(msg)
        eval_entry = result.payload["evaluations"][0]
        assert eval_entry["scoring_mode"] == "evaluator"
        assert eval_entry["quality_score"] == 1.0

    def test_injected_low_score_evaluator_triggers_retry(self):
        """Low-scoring injected evaluator triggers retry verdict."""
        class LowScoreEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=0.1, passed=False)

        mw = EvaluationMiddleware(
            quality_threshold=0.5,
            max_retries=3,
            evaluator=LowScoreEval(),
        )
        msg = _make_message({"output": "something"})
        result = mw.process(msg)
        eval_entry = result.payload["evaluations"][0]
        assert eval_entry["scoring_mode"] == "evaluator"
        assert result.payload["overall_verdict"] in ("retry", "escalate")

    def test_evaluator_fallback_on_failure(self):
        """If evaluator raises, falls back to heuristic scoring."""
        class BrokenEval:
            def evaluate(self, context, output):
                raise RuntimeError("eval broken")

        mw = EvaluationMiddleware(
            quality_threshold=0.5,
            evaluator=BrokenEval(),
        )
        msg = _make_message({"output": "something"})
        # Should not raise, falls back to heuristic
        result = mw.process(msg)
        eval_entry = result.payload["evaluations"][0]
        assert eval_entry["scoring_mode"] == "heuristic"

    def test_evaluator_id_recorded_when_evaluator_used(self):
        """evaluator_id in result matches the evaluator class name."""
        class MyEval:
            def evaluate(self, context, output):
                from hi_agent.evaluation.contracts import EvaluationResult
                return EvaluationResult(score=0.9, passed=True)

        mw = EvaluationMiddleware(quality_threshold=0.5, evaluator=MyEval())
        msg = _make_message({"output": "x"})
        result = mw.process(msg)
        entry = result.payload["evaluations"][0]
        assert entry["evaluator_id"] == "MyEval"
        assert entry["fallback_reason"] == ""

    def test_fallback_reason_recorded_on_evaluator_failure(self):
        """When evaluator raises, fallback_reason records the exception."""
        class BrokenEval:
            def evaluate(self, context, output):
                raise RuntimeError("eval broke")

        mw = EvaluationMiddleware(quality_threshold=0.5, evaluator=BrokenEval())
        msg = _make_message({"output": "x"})
        result = mw.process(msg)
        entry = result.payload["evaluations"][0]
        assert entry["scoring_mode"] == "heuristic"
        assert "BrokenEval" in entry["evaluator_id"]
        assert "eval broke" in entry["fallback_reason"]
