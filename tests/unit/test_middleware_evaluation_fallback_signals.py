"""Track W2-D regression: EvaluationMiddleware LLM-error fallback emits Rule-7 signals.

When ``_llm_evaluate`` raises, ``_assess_quality`` falls back to
``_heuristic_score``.  That fallback must be loud (countable +
attributable + inspectable) per Rule 7.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.middleware.evaluation import EvaluationMiddleware
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events


def test_evaluator_records_fallback_on_llm_error() -> None:
    """LLM exception during evaluator scoring -> heuristic score + fallback event."""
    run_id = "test-w2d-eval-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    gateway.complete.side_effect = RuntimeError("LLM gateway exploded")

    mw = EvaluationMiddleware(llm_gateway=gateway, quality_threshold=0.6)

    score, mode, meta = mw._assess_quality(
        node_id="n1",
        output="some non-trivial output that should heuristically pass threshold",
        evidence=["e1", "e2"],
        task_goal="explain X",
        run_id=run_id,
    )

    # Behavioural invariant: heuristic mode returned (not "llm").
    assert mode == "heuristic"
    assert 0.0 <= score <= 1.0
    assert meta["evaluator_id"] == "heuristic"

    events = get_fallback_events(run_id)
    assert any(
        e["reason"] == "llm_evaluator_failed_heuristic_score" for e in events
    ), events
    match = next(
        e for e in events if e["reason"] == "llm_evaluator_failed_heuristic_score"
    )
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "EvaluationMiddleware._assess_quality"
    assert match["extra"]["node_id"] == "n1"
    assert match["extra"]["error_type"] == "RuntimeError"
