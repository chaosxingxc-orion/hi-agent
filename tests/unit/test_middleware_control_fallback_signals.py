"""Track W2-D regression: ControlMiddleware LLM-error fallback emits Rule-7 signals.

When ``_llm_decompose`` raises, ``_decompose`` falls back to the
deterministic ``_DEFAULT_STAGES`` plan.  That fallback must be loud
(countable + attributable + inspectable) per Rule 7.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.middleware.control import _DEFAULT_STAGES, ControlMiddleware
from hi_agent.middleware.protocol import MiddlewareMessage
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events


def test_stage_decompose_records_fallback_on_llm_error() -> None:
    """LLM exception during stage decompose -> default plan + fallback event."""
    run_id = "test-w2d-control-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    gateway.complete.side_effect = RuntimeError("LLM timeout")

    mw = ControlMiddleware(llm_gateway=gateway)
    msg = MiddlewareMessage(
        source="perception",
        target="control",
        msg_type="perception_result",
        payload={"raw_text": "do the task", "metadata": {}},
        metadata={"run_id": run_id},
    )

    out = mw.process(msg)

    # Behavioural invariant: default plan kicks in unchanged.
    nodes = out.payload["graph_json"]["nodes"]
    assert len(nodes) == len(_DEFAULT_STAGES)
    # Default plan signature: (stage_id, description) tuples match.
    actual = [(n["node_id"], n["payload"]["description"]) for n in nodes]
    expected = [(s[0], s[1]) for s in _DEFAULT_STAGES]
    assert actual == expected

    events = get_fallback_events(run_id)
    assert any(
        e["reason"] == "llm_stage_decompose_failed_default_plan" for e in events
    ), events
    match = next(
        e for e in events if e["reason"] == "llm_stage_decompose_failed_default_plan"
    )
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "ControlMiddleware._decompose"
    assert match["extra"]["error_type"] == "RuntimeError"
    assert match["extra"]["default_stage_count"] == len(_DEFAULT_STAGES)
