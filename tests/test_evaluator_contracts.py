"""Tests for hi_agent.evaluation contracts and plugin interface."""

from __future__ import annotations

import pytest
from hi_agent.evaluation.contracts import (
    CompositeEvaluator,
    DefaultEvaluator,
    EvaluationContext,
    EvaluationResult,
    Evaluator,
)

# ---------------------------------------------------------------------------
# EvaluationContext
# ---------------------------------------------------------------------------

class TestEvaluationContext:
    def test_defaults(self):
        ctx = EvaluationContext(goal="Do something")
        assert ctx.stage_id == ""
        assert ctx.acceptance_criteria == []
        assert ctx.evidence == []
        assert ctx.metadata == {}

    def test_full_creation(self):
        ctx = EvaluationContext(
            goal="Summarize the report",
            stage_id="S4_synthesize",
            acceptance_criteria=["must be ≥100 words", "must cite 3 sources"],
            evidence=[{"claim": "Revenue grew", "confidence": 0.9}],
            metadata={"run_id": "r1"},
        )
        assert ctx.stage_id == "S4_synthesize"
        assert len(ctx.acceptance_criteria) == 2
        assert len(ctx.evidence) == 1


# ---------------------------------------------------------------------------
# EvaluationResult
# ---------------------------------------------------------------------------

class TestEvaluationResult:
    def test_creation(self):
        r = EvaluationResult(score=0.8, passed=True)
        assert r.score == 0.8
        assert r.passed is True
        assert r.criteria_results == {}
        assert r.feedback == ""
        assert r.suggestions == []

    def test_with_criteria(self):
        r = EvaluationResult(
            score=0.6,
            passed=True,
            criteria_results={"completeness": True, "accuracy": False},
            feedback="partial",
            suggestions=["Add citations"],
        )
        assert r.criteria_results["completeness"] is True
        assert r.criteria_results["accuracy"] is False
        assert "Add citations" in r.suggestions


# ---------------------------------------------------------------------------
# Evaluator protocol
# ---------------------------------------------------------------------------

class TestEvaluatorProtocol:
    def test_default_evaluator_satisfies_protocol(self):
        ev = DefaultEvaluator()
        assert isinstance(ev, Evaluator)

    def test_custom_class_satisfies_protocol(self):
        class MyEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=1.0, passed=True, feedback="custom")

        ev = MyEval()
        assert isinstance(ev, Evaluator)

    def test_missing_evaluate_method_fails_protocol(self):
        class NotAnEval:
            pass

        assert not isinstance(NotAnEval(), Evaluator)


# ---------------------------------------------------------------------------
# DefaultEvaluator
# ---------------------------------------------------------------------------

class TestDefaultEvaluator:
    def _ctx(self) -> EvaluationContext:
        return EvaluationContext(goal="Test goal")

    def test_empty_output_fails(self):
        ev = DefaultEvaluator(threshold=0.5)
        result = ev.evaluate(self._ctx(), {})
        assert result.score < 0.5
        assert result.passed is False

    def test_minimal_output(self):
        ev = DefaultEvaluator(threshold=0.5)
        result = ev.evaluate(self._ctx(), {"output": "some text"})
        # non_empty + has_output_key + no_error + score_meaningful(no score) = 4/5
        assert result.score >= 0.5
        assert result.passed is True

    def test_full_output_passes(self):
        ev = DefaultEvaluator(threshold=0.5)
        output = {
            "output": "Detailed analysis",
            "evidence": [{"claim": "fact", "source": "paper"}],
            "score": 0.85,
        }
        result = ev.evaluate(self._ctx(), output)
        assert result.score >= 0.8
        assert result.passed is True

    def test_output_with_error_field_fails(self):
        ev = DefaultEvaluator(threshold=0.5)
        result = ev.evaluate(self._ctx(), {"output": "text", "error": "something went wrong"})
        assert result.criteria_results["no_error"] is False

    def test_output_success_false_penalized(self):
        ev = DefaultEvaluator(threshold=0.5)
        result = ev.evaluate(self._ctx(), {"output": "text", "success": False})
        assert result.criteria_results["no_error"] is False

    def test_threshold_configurable(self):
        ev_strict = DefaultEvaluator(threshold=0.9)
        ev_lenient = DefaultEvaluator(threshold=0.2)
        output = {"output": "text"}
        strict_result = ev_strict.evaluate(self._ctx(), output)
        lenient_result = ev_lenient.evaluate(self._ctx(), output)
        # Same score, different pass/fail
        assert strict_result.score == lenient_result.score
        assert strict_result.passed is False
        assert lenient_result.passed is True

    def test_criteria_in_result(self):
        ev = DefaultEvaluator()
        result = ev.evaluate(self._ctx(), {"output": "text"})
        assert "non_empty" in result.criteria_results
        assert "has_output_key" in result.criteria_results
        assert "has_evidence" in result.criteria_results
        assert "score_meaningful" in result.criteria_results
        assert "no_error" in result.criteria_results

    def test_suggestions_when_missing_keys(self):
        ev = DefaultEvaluator()
        result = ev.evaluate(self._ctx(), {"output": "text"})
        # Missing evidence → should suggest adding it
        assert any("evidence" in s.lower() or "source" in s.lower() for s in result.suggestions)


# ---------------------------------------------------------------------------
# CompositeEvaluator
# ---------------------------------------------------------------------------

class TestCompositeEvaluator:
    def _ctx(self) -> EvaluationContext:
        return EvaluationContext(goal="Test")

    def test_single_evaluator(self):
        ev = CompositeEvaluator([(DefaultEvaluator(), 1.0)])
        output = {"output": "text", "evidence": ["e1"], "score": 0.8}
        result = ev.evaluate(self._ctx(), output)
        assert result.score > 0.5

    def test_weighted_average(self):
        class AlwaysHigh:
            def evaluate(self, context, output):
                return EvaluationResult(score=1.0, passed=True)

        class AlwaysLow:
            def evaluate(self, context, output):
                return EvaluationResult(score=0.0, passed=False)

        composite = CompositeEvaluator([(AlwaysHigh(), 1.0), (AlwaysLow(), 1.0)])
        result = composite.evaluate(self._ctx(), {})
        assert abs(result.score - 0.5) < 0.01

    def test_all_must_pass(self):
        class PassEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=0.9, passed=True)

        class FailEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=0.0, passed=False)

        composite = CompositeEvaluator([(PassEval(), 1.0), (FailEval(), 1.0)])
        result = composite.evaluate(self._ctx(), {})
        assert result.passed is False  # both must pass

    def test_all_pass_if_all_pass(self):
        class PassEval:
            def evaluate(self, context, output):
                return EvaluationResult(score=0.9, passed=True)

        composite = CompositeEvaluator([(PassEval(), 1.0), (PassEval(), 1.0)])
        result = composite.evaluate(self._ctx(), {"output": "x"})
        assert result.passed is True

    def test_empty_evaluators_raises(self):
        with pytest.raises(ValueError):
            CompositeEvaluator([])

    def test_merged_criteria(self):
        class EvalA:
            def evaluate(self, context, output):
                return EvaluationResult(score=1.0, passed=True, criteria_results={"a": True})

        class EvalB:
            def evaluate(self, context, output):
                return EvaluationResult(score=1.0, passed=True, criteria_results={"b": False})

        composite = CompositeEvaluator([(EvalA(), 1.0), (EvalB(), 1.0)])
        result = composite.evaluate(self._ctx(), {})
        assert "a" in result.criteria_results
        assert "b" in result.criteria_results

    def test_integration_with_context(self):
        """CompositeEvaluator works with realistic EvaluationContext."""
        ctx = EvaluationContext(
            goal="Analyze quarterly revenue",
            stage_id="S4_synthesize",
            acceptance_criteria=["Include trend analysis", "Cite sources"],
            evidence=[{"claim": "Revenue up 10%", "confidence": 0.9}],
        )
        output = {
            "output": "Revenue increased by 10% year-over-year.",
            "evidence": [{"claim": "Revenue up", "source": "Q3 report"}],
            "score": 0.85,
        }
        ev = CompositeEvaluator([(DefaultEvaluator(threshold=0.5), 1.0)])
        result = ev.evaluate(ctx, output)
        assert result.passed is True
        assert result.score > 0.7
