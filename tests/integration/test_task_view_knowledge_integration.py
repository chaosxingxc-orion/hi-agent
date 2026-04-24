"""Tests for knowledge-query helper in task view builder."""

from __future__ import annotations

from hi_agent.contracts import RunIndex, StageSummary
from hi_agent.task_view.builder import build_task_view_with_knowledge_query


def _make_stage_summary(stage_id: str) -> StageSummary:
    return StageSummary(
        stage_id=stage_id,
        stage_name=stage_id,
        findings=[f"finding:{stage_id}"],
        decisions=[f"decision:{stage_id}"],
        outcome="completed",
    )


def test_build_task_view_with_knowledge_query_calls_query_with_expected_args() -> None:
    """Helper should call injected query function with query_text and top_k."""
    captured: dict[str, object] = {}

    def _query(*, query_text: str, top_k: int) -> list[object]:
        captured["query_text"] = query_text
        captured["top_k"] = top_k
        return ["k-1", "k-2"]

    run_index = RunIndex(run_id="run-1", current_stage="S2_plan")
    stage_summaries = {
        "S1_understand": _make_stage_summary("S1_understand"),
        "S2_plan": _make_stage_summary("S2_plan"),
    }
    view = build_task_view_with_knowledge_query(
        run_index=run_index,
        stage_summaries=stage_summaries,
        episodes=[],
        query_text="schema rollback",
        knowledge_query_fn=_query,
        top_k=2,
        budget=8,
    )

    assert captured == {"query_text": "schema rollback", "top_k": 2}
    assert view["knowledge"] == ["k-1", "k-2"]


def test_build_task_view_with_knowledge_query_respects_budget() -> None:
    """Knowledge from query should still be truncated by layered budget rules."""

    def _query(*, query_text: str, top_k: int) -> list[object]:
        assert query_text == "q"
        assert top_k == 5
        return ["k-1", "k-2", "k-3", "k-4"]

    run_index = RunIndex(run_id="run-2", current_stage="S2_plan")
    stage_summaries = {
        "S1_understand": _make_stage_summary("S1_understand"),
        "S2_plan": _make_stage_summary("S2_plan"),
    }
    view = build_task_view_with_knowledge_query(
        run_index=run_index,
        stage_summaries=stage_summaries,
        episodes=["ep-1", "ep-2"],
        query_text="q",
        knowledge_query_fn=_query,
        top_k=5,
        budget=5,
    )

    # budget=5 => run_index/current/previous consume 3, episodes consume 2.
    assert view["episodes"] == ["ep-1", "ep-2"]
    assert view["knowledge"] == []
