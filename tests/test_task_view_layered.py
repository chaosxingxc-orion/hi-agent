"""Tests for layered task view builder (token-budget based)."""

from __future__ import annotations

from hi_agent.contracts import RunIndex, StageSummary
from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.l2_index import RunMemoryIndex
from hi_agent.task_view.builder import (
    TaskView,
    TaskViewSection,
    build_task_view,
    format_episodes,
    format_knowledge,
    format_run_index,
    format_stage_summary,
)
from hi_agent.task_view.token_budget import (
    DEFAULT_BUDGET,
    LAYER_BUDGETS,
    count_tokens,
    enforce_layer_budget,
    set_token_counter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_index(run_id: str = "run-1", stages: list[tuple[str, str]] | None = None) -> RunMemoryIndex:
    idx = RunMemoryIndex(run_id=run_id)
    for sid, outcome in (stages or []):
        idx.add_stage(sid, outcome)
    return idx


def _make_stage(
    stage_id: str = "S1",
    findings: list[str] | None = None,
    decisions: list[str] | None = None,
    outcome: str = "active",
) -> CompressedStageMemory:
    return CompressedStageMemory(
        stage_id=stage_id,
        findings=findings or [f"finding-{stage_id}"],
        decisions=decisions or [f"decision-{stage_id}"],
        outcome=outcome,
        key_entities=["entity-a"],
        source_evidence_count=5,
    )


# Legacy helpers for backward-compat tests
def _make_legacy_stage_summary(stage_id: str) -> StageSummary:
    return StageSummary(
        stage_id=stage_id,
        stage_name=stage_id,
        findings=[f"finding:{stage_id}"],
        decisions=[f"decision:{stage_id}"],
        outcome="completed",
    )


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_basic_heuristic(self) -> None:
        assert count_tokens("abcd") == 1
        assert count_tokens("abcdefgh") == 2

    def test_minimum_one(self) -> None:
        assert count_tokens("") == 1
        assert count_tokens("a") == 1

    def test_pluggable_counter(self) -> None:
        set_token_counter(lambda text: len(text))
        try:
            assert count_tokens("hello") == 5
        finally:
            set_token_counter(None)

    def test_restore_default(self) -> None:
        # After resetting, default heuristic should be back
        assert count_tokens("abcdefgh") == 2


# ---------------------------------------------------------------------------
# enforce_layer_budget
# ---------------------------------------------------------------------------


class TestEnforceLayerBudget:
    def test_no_truncation_needed(self) -> None:
        text = "short"
        assert enforce_layer_budget(text, 100) == text

    def test_truncation(self) -> None:
        text = "a" * 100  # 25 tokens
        result = enforce_layer_budget(text, 10)
        assert count_tokens(result) <= 10

    def test_zero_budget(self) -> None:
        assert enforce_layer_budget("anything", 0) == ""

    def test_negative_budget(self) -> None:
        assert enforce_layer_budget("anything", -5) == ""


# ---------------------------------------------------------------------------
# Format functions
# ---------------------------------------------------------------------------


class TestFormatRunIndex:
    def test_basic(self) -> None:
        idx = _make_index("run-42", [("S1", "succeeded"), ("S2", "active")])
        text = format_run_index(idx)
        assert "run-42" in text
        assert "S1: succeeded" in text
        assert "S2: active" in text

    def test_empty_stages(self) -> None:
        idx = _make_index("run-0")
        text = format_run_index(idx)
        assert "run-0" in text


class TestFormatStageSummary:
    def test_basic(self) -> None:
        s = _make_stage("S2", findings=["f1", "f2"], decisions=["d1"])
        text = format_stage_summary(s)
        assert "S2" in text
        assert "f1" in text
        assert "d1" in text
        assert "entity-a" in text

    def test_empty_fields(self) -> None:
        s = CompressedStageMemory(stage_id="S0")
        text = format_stage_summary(s)
        assert "S0" in text
        assert "Findings" not in text


class TestFormatEpisodes:
    def test_basic(self) -> None:
        eps = [{"event": "did-thing"}, {"event": "other"}]
        text = format_episodes(eps, max_tokens=500)
        assert "did-thing" in text

    def test_truncation(self) -> None:
        eps = [{"data": "x" * 100}] * 10
        text = format_episodes(eps, max_tokens=10)
        # Should contain fewer than all 10 episodes
        assert count_tokens(text) <= 10 or text == ""

    def test_empty(self) -> None:
        assert format_episodes([], max_tokens=100) == ""

    def test_zero_budget(self) -> None:
        assert format_episodes([{"a": 1}], max_tokens=0) == ""


class TestFormatKnowledge:
    def test_basic_strings(self) -> None:
        text = format_knowledge(["fact-1", "fact-2"], max_tokens=500)
        assert "fact-1" in text

    def test_with_content_attr(self) -> None:
        class _FakeRecord:
            key = "k1"
            content = "important fact"

        text = format_knowledge([_FakeRecord()], max_tokens=500)
        assert "important fact" in text

    def test_empty(self) -> None:
        assert format_knowledge([], max_tokens=100) == ""


# ---------------------------------------------------------------------------
# build_task_view — new layered path
# ---------------------------------------------------------------------------


class TestBuildTaskViewLayered:
    def test_full_build_all_layers(self) -> None:
        idx = _make_index("run-1", [("S1", "succeeded"), ("S2", "active")])
        cur = _make_stage("S2")
        prev = _make_stage("S1", outcome="succeeded")
        eps = [{"event": "action-1"}]
        kr = ["knowledge-fact"]

        view = build_task_view(
            run_index=idx,
            current_stage_summary=cur,
            previous_stage_summary=prev,
            episodes=eps,
            knowledge_records=kr,
        )

        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "l2_index" in layers
        assert "l1_current_stage" in layers
        assert "l1_previous_stage" in layers
        assert "l3_episodic" in layers
        assert "knowledge" in layers
        assert view.total_tokens > 0
        assert view.budget == DEFAULT_BUDGET
        assert 0.0 < view.budget_utilization <= 1.0

    def test_minimal_l2_and_l1_current(self) -> None:
        idx = _make_index("run-2", [("S1", "active")])
        cur = _make_stage("S1")

        view = build_task_view(run_index=idx, current_stage_summary=cur)

        assert isinstance(view, TaskView)
        layers = [s.layer for s in view.sections]
        assert "l2_index" in layers
        assert "l1_current_stage" in layers
        assert "l1_previous_stage" not in layers
        assert "l3_episodic" not in layers
        assert "knowledge" not in layers

    def test_budget_overflow_drops_lower_priority(self) -> None:
        """With a tiny budget, lower-priority layers get dropped."""
        idx = _make_index("run-3", [("S1", "done")])
        cur = _make_stage("S1")
        prev = _make_stage("S0")
        eps = [{"e": "val"}]
        kr = ["fact"]

        # Very tight budget: system_reserved=512 leaves almost nothing
        view = build_task_view(
            run_index=idx,
            current_stage_summary=cur,
            previous_stage_summary=prev,
            episodes=eps,
            knowledge_records=kr,
            budget=520,
        )

        assert isinstance(view, TaskView)
        # Only 8 tokens left after system_reserved; some layers must be dropped
        # The exact layers depend on content size but total should respect budget
        assert view.total_tokens <= 520

    def test_empty_inputs(self) -> None:
        view = build_task_view()
        assert isinstance(view, TaskView)
        assert view.sections == []
        # total_tokens should be system_reserved only
        assert view.total_tokens == LAYER_BUDGETS["system_reserved"]

    def test_budget_utilization_calculation(self) -> None:
        idx = _make_index("r", [("S1", "ok")])
        view = build_task_view(run_index=idx, budget=10000)
        assert isinstance(view, TaskView)
        expected = view.total_tokens / 10000
        assert abs(view.budget_utilization - expected) < 0.001

    def test_system_reserved_always_deducted(self) -> None:
        """total_tokens includes system_reserved even with no content."""
        view = build_task_view(budget=2000)
        assert isinstance(view, TaskView)
        assert view.total_tokens >= LAYER_BUDGETS["system_reserved"]

    def test_negative_budget_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="non-negative"):
            build_task_view(budget=-1)

    def test_zero_budget(self) -> None:
        view = build_task_view(
            run_index=_make_index("r"),
            current_stage_summary=_make_stage(),
            budget=0,
        )
        assert isinstance(view, TaskView)
        assert view.sections == []
        assert view.total_tokens == 0

    def test_deterministic(self) -> None:
        """Same inputs always produce the same output."""
        kwargs = dict(
            run_index=_make_index("r", [("S1", "ok")]),
            current_stage_summary=_make_stage("S1"),
            episodes=[{"x": 1}],
            knowledge_records=["fact"],
            budget=5000,
        )
        v1 = build_task_view(**kwargs)
        v2 = build_task_view(**kwargs)
        assert isinstance(v1, TaskView)
        assert isinstance(v2, TaskView)
        assert v1.total_tokens == v2.total_tokens
        assert len(v1.sections) == len(v2.sections)
        for s1, s2 in zip(v1.sections, v2.sections):
            assert s1.layer == s2.layer
            assert s1.content == s2.content
            assert s1.token_count == s2.token_count


# ---------------------------------------------------------------------------
# Legacy path — backward compatibility
# ---------------------------------------------------------------------------


class TestBuildTaskViewLegacy:
    def test_prioritizes_index_and_stage_summaries(self) -> None:
        """Higher-priority sections should be kept first when budget is tight."""
        run_index = RunIndex(run_id="run-1", current_stage="S2_plan")
        stage_summaries = {
            "S1_understand": _make_legacy_stage_summary("S1_understand"),
            "S2_plan": _make_legacy_stage_summary("S2_plan"),
        }

        view = build_task_view(
            run_index=run_index,
            stage_summaries=stage_summaries,
            episodes=["ep-1", "ep-2"],
            knowledge=["kg-1", "kg-2"],
            budget=3,
        )

        assert view["run_index"] == run_index
        assert view["current_stage_summary"] == stage_summaries["S2_plan"]
        assert view["previous_stage_summary"] == stage_summaries["S1_understand"]
        assert view["episodes"] == []
        assert view["knowledge"] == []
        assert view["used_items"] == 3

    def test_truncates_episodes_then_knowledge(self) -> None:
        """Lower-priority sections should be truncated by remaining budget."""
        run_index = RunIndex(run_id="run-2", current_stage="S2_plan")
        stage_summaries = {
            "S1_understand": _make_legacy_stage_summary("S1_understand"),
            "S2_plan": _make_legacy_stage_summary("S2_plan"),
        }

        view = build_task_view(
            run_index=run_index,
            stage_summaries=stage_summaries,
            episodes=["ep-1", "ep-2", "ep-3"],
            knowledge=["kg-1", "kg-2", "kg-3"],
            budget=7,
        )

        assert view["episodes"] == ["ep-1", "ep-2", "ep-3"]
        assert view["knowledge"] == ["kg-1"]
        assert view["used_items"] == 7
