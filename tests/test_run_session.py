"""Tests for the RunSession module and CostCalculator."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pytest
from hi_agent.session.cost_tracker import CostCalculator, ModelPricing
from hi_agent.session.run_session import (
    LLMCallRecord,
    RunSession,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeContract:
    task_id: str = "t-001"
    goal: str = "Summarize the document"


def _make_session(**kwargs) -> RunSession:
    return RunSession(
        run_id="run-abc",
        task_contract=_FakeContract(),
        **kwargs,
    )


def _make_llm_call(
    call_id: str = "c1",
    purpose: str = "action",
    stage_id: str = "S1",
    model: str = "claude-sonnet-4",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cost_usd: float = 0.01,
) -> LLMCallRecord:
    return LLMCallRecord(
        call_id=call_id,
        purpose=purpose,
        stage_id=stage_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# RunSession creation and state initialization
# ---------------------------------------------------------------------------


class TestRunSessionCreation:
    def test_initial_state(self) -> None:
        s = _make_session()
        assert s.run_id == "run-abc"
        assert s.task_contract.goal == "Summarize the document"
        assert s.l0_records == []
        assert s.l1_summaries == {}
        assert s.events == []
        assert s.current_stage == ""
        assert s.stage_states == {}
        assert s.action_seq == 0
        assert s.branch_seq == 0
        assert s.llm_calls == []
        assert s.total_input_tokens == 0
        assert s.total_output_tokens == 0
        assert s.total_cost_usd == 0.0
        assert s.last_compact_boundary is None


# ---------------------------------------------------------------------------
# L0 append_record — in-memory and JSONL persistence
# ---------------------------------------------------------------------------


class TestAppendRecord:
    def test_append_stores_in_memory(self) -> None:
        s = _make_session()
        s.current_stage = "S1"
        idx = s.append_record("observation", {"key": "val"})
        assert idx == 0
        assert len(s.l0_records) == 1
        rec = s.l0_records[0]
        assert rec["event_type"] == "observation"
        assert rec["payload"] == {"key": "val"}
        assert rec["stage_id"] == "S1"

    def test_append_persists_to_jsonl(self, tmp_path) -> None:
        storage = str(tmp_path / "store")
        s = _make_session(storage_dir=storage)
        s.append_record("obs", {"x": 1})
        s.append_record("obs", {"x": 2})

        jsonl_path = os.path.join(storage, "l0_run-abc.jsonl")
        assert os.path.exists(jsonl_path)
        with open(jsonl_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["payload"] == {"x": 1}

    def test_append_explicit_stage(self) -> None:
        s = _make_session()
        s.current_stage = "S1"
        s.append_record("obs", {}, stage_id="S3")
        assert s.l0_records[0]["stage_id"] == "S3"


# ---------------------------------------------------------------------------
# get_records_after_boundary
# ---------------------------------------------------------------------------


class TestRecordsAfterBoundary:
    def test_no_boundary_returns_all(self) -> None:
        s = _make_session()
        s.append_record("a", {})
        s.append_record("b", {})
        assert len(s.get_records_after_boundary()) == 2

    def test_boundary_filters(self) -> None:
        s = _make_session()
        s.append_record("a", {})
        s.append_record("b", {})
        s.mark_compact_boundary("S1")  # boundary at index 1
        s.append_record("c", {})
        fresh = s.get_records_after_boundary()
        assert len(fresh) == 1
        assert fresh[0]["event_type"] == "c"


# ---------------------------------------------------------------------------
# mark_compact_boundary
# ---------------------------------------------------------------------------


class TestCompactBoundary:
    def test_mark_and_retrieve(self) -> None:
        s = _make_session()
        s.append_record("x", {})
        s.mark_compact_boundary("S1", summary_ref="sum-001")
        b = s.last_compact_boundary
        assert b is not None
        assert b.stage_id == "S1"
        assert b.event_offset == 0
        assert b.summary_ref == "sum-001"

    def test_multiple_boundaries(self) -> None:
        s = _make_session()
        s.append_record("x", {})
        s.mark_compact_boundary("S1")
        s.append_record("y", {})
        s.append_record("z", {})
        s.mark_compact_boundary("S2")
        assert s.last_compact_boundary.stage_id == "S2"
        assert s.last_compact_boundary.event_offset == 2


# ---------------------------------------------------------------------------
# L1 stage summaries
# ---------------------------------------------------------------------------


class TestStageSummaries:
    def test_set_and_get(self) -> None:
        s = _make_session()
        s.set_stage_summary("S1", {"findings": "done"})
        assert s.get_stage_summary("S1") == {"findings": "done"}

    def test_get_missing_returns_none(self) -> None:
        s = _make_session()
        assert s.get_stage_summary("S99") is None


# ---------------------------------------------------------------------------
# LLM call tracking
# ---------------------------------------------------------------------------


class TestLLMCallTracking:
    def test_record_accumulates_costs(self) -> None:
        s = _make_session()
        s.record_llm_call(_make_llm_call(cost_usd=0.05, input_tokens=1000, output_tokens=500))
        s.record_llm_call(
            _make_llm_call(call_id="c2", cost_usd=0.03, input_tokens=800, output_tokens=200)
        )
        assert len(s.llm_calls) == 2
        assert s.total_cost_usd == pytest.approx(0.08)
        assert s.total_input_tokens == 1800
        assert s.total_output_tokens == 700

    def test_get_cost_summary(self) -> None:
        s = _make_session()
        s.record_llm_call(_make_llm_call(stage_id="S1", purpose="routing", cost_usd=0.01))
        s.record_llm_call(
            _make_llm_call(call_id="c2", stage_id="S2", purpose="action", cost_usd=0.02)
        )
        s.record_llm_call(
            _make_llm_call(call_id="c3", stage_id="S1", purpose="action", cost_usd=0.03)
        )
        summary = s.get_cost_summary()
        assert summary["total_llm_calls"] == 3
        assert summary["total_cost_usd"] == pytest.approx(0.06)
        assert summary["by_stage"]["S1"] == pytest.approx(0.04)
        assert summary["by_stage"]["S2"] == pytest.approx(0.02)
        assert summary["by_purpose"]["routing"] == pytest.approx(0.01)
        assert summary["by_purpose"]["action"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Event tracking
# ---------------------------------------------------------------------------


class TestEventTracking:
    def test_emit_event_stores(self) -> None:
        s = _make_session()
        ev = s.emit_event("stage_entered", {"stage": "S1"})
        assert len(s.events) == 1
        assert ev["event_type"] == "stage_entered"
        assert ev["run_id"] == "run-abc"
        assert ev["payload"]["stage"] == "S1"
        assert "timestamp" in ev


# ---------------------------------------------------------------------------
# Checkpoint round-trip (in-memory)
# ---------------------------------------------------------------------------


class TestCheckpointRoundTrip:
    def test_to_and_from_checkpoint(self) -> None:
        s = _make_session()
        s.current_stage = "S2"
        s.stage_states = {"S1": "completed", "S2": "active"}
        s.action_seq = 5
        s.branch_seq = 2
        s.append_record("obs", {"data": 42})
        s.set_stage_summary("S1", {"summary": "ok"})
        s.emit_event("ev", {"x": 1})
        s.record_llm_call(_make_llm_call(cost_usd=0.07))
        s.mark_compact_boundary("S1", summary_ref="ref-1")

        cp = s.to_checkpoint()
        restored = RunSession.from_checkpoint(cp, task_contract=_FakeContract())

        assert restored.run_id == "run-abc"
        assert restored.current_stage == "S2"
        assert restored.stage_states == {"S1": "completed", "S2": "active"}
        assert restored.action_seq == 5
        assert restored.branch_seq == 2
        assert len(restored.l0_records) == 1
        assert restored.l1_summaries["S1"] == {"summary": "ok"}
        assert len(restored.events) == 1
        assert len(restored.llm_calls) == 1
        assert restored.total_cost_usd == pytest.approx(0.07)
        assert restored.last_compact_boundary is not None
        assert restored.last_compact_boundary.stage_id == "S1"


# ---------------------------------------------------------------------------
# Checkpoint file round-trip
# ---------------------------------------------------------------------------


class TestCheckpointFilePersistence:
    def test_save_and_load(self, tmp_path) -> None:
        s = _make_session()
        s.current_stage = "S3"
        s.append_record("obs", {"v": 99})
        s.record_llm_call(_make_llm_call())

        path = str(tmp_path / "ckpt.json")
        returned_path = s.save_checkpoint(path)
        assert returned_path == path
        assert os.path.exists(path)

        loaded = RunSession.load_checkpoint(path, task_contract=_FakeContract())
        assert loaded.run_id == "run-abc"
        assert loaded.current_stage == "S3"
        assert len(loaded.l0_records) == 1
        assert len(loaded.llm_calls) == 1


# ---------------------------------------------------------------------------
# load_l0_from_disk
# ---------------------------------------------------------------------------


class TestLoadL0FromDisk:
    def test_restore_records(self, tmp_path) -> None:
        storage = str(tmp_path / "l0store")
        s1 = _make_session(storage_dir=storage)
        s1.append_record("a", {"n": 1})
        s1.append_record("b", {"n": 2})
        assert len(s1.l0_records) == 2

        # New session, same storage
        s2 = _make_session(storage_dir=storage)
        assert len(s2.l0_records) == 0
        loaded = s2.load_l0_from_disk()
        assert loaded == 2
        assert len(s2.l0_records) == 2
        assert s2.l0_records[0]["payload"] == {"n": 1}

    def test_no_storage_dir_returns_zero(self) -> None:
        s = _make_session()
        assert s.load_l0_from_disk() == 0


# ---------------------------------------------------------------------------
# build_context_for_llm
# ---------------------------------------------------------------------------


class TestBuildContextForLLM:
    def test_respects_budget(self) -> None:
        s = _make_session()
        s.current_stage = "S1"
        # Add many records
        for _i in range(200):
            s.append_record("obs", {"data": "x" * 100})

        ctx = s.build_context_for_llm("routing", budget_tokens=512)
        # Should not include all 200 records
        assert len(ctx["fresh_evidence"]) < 200
        assert ctx["budget_used_tokens"] <= 512

    def test_uses_compact_boundary_for_dedup(self) -> None:
        s = _make_session()
        s.current_stage = "S1"
        s.append_record("old", {"v": "old_data"})
        s.set_stage_summary("S1", {"compressed": True})
        s.mark_compact_boundary("S1")
        s.current_stage = "S2"
        s.append_record("new", {"v": "new_data"})

        ctx = s.build_context_for_llm("action", budget_tokens=8192)
        # Fresh evidence should only contain the record after boundary
        assert len(ctx["fresh_evidence"]) == 1
        assert "new_data" in ctx["fresh_evidence"][0]
        assert ctx["compact_boundary"] is not None
        assert ctx["compact_boundary"]["stage_id"] == "S1"

    def test_includes_l1_summaries(self) -> None:
        s = _make_session()
        s.set_stage_summary("S1", {"key": "summarized"})
        ctx = s.build_context_for_llm("routing")
        assert "S1" in ctx["stage_summaries"]

    def test_no_boundary_returns_null(self) -> None:
        s = _make_session()
        ctx = s.build_context_for_llm("routing")
        assert ctx["compact_boundary"] is None


# ---------------------------------------------------------------------------
# CostCalculator
# ---------------------------------------------------------------------------


class TestCostCalculator:
    def test_known_model(self) -> None:
        calc = CostCalculator()
        # claude-sonnet-4: input=3.0/Mtok, output=15.0/Mtok
        cost = calc.calculate("claude-sonnet-4", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(18.0)

    def test_with_cache_tokens(self) -> None:
        calc = CostCalculator()
        # claude-opus-4: input=15, output=75, cache_write=18.75, cache_read=1.5
        cost = calc.calculate(
            "claude-opus-4",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_tokens=1_000_000,
            cache_creation_tokens=1_000_000,
        )
        # 15 + 0 + 1.5 + 18.75 = 35.25
        assert cost == pytest.approx(35.25)

    def test_prefix_matching(self) -> None:
        calc = CostCalculator()
        # "claude-sonnet-4-20260514" should match "claude-sonnet-4"
        cost = calc.calculate(
            "claude-sonnet-4-20260514",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        assert cost == pytest.approx(3.0)

    def test_unknown_model_returns_zero(self) -> None:
        calc = CostCalculator()
        cost = calc.calculate("unknown-model-xyz", input_tokens=999_999, output_tokens=999_999)
        assert cost == 0.0

    def test_custom_pricing(self) -> None:
        custom = {"my-model": ModelPricing(1.0, 2.0)}
        calc = CostCalculator(custom_pricing=custom)
        cost = calc.calculate("my-model", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(3.0)
