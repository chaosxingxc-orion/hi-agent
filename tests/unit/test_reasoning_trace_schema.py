"""Unit tests: ReasoningTraceEntry and ReasoningTrace schema (TE-5).

Verifies the contract fields, default values, and dict serialization without
any mock or external dependency.
"""
from __future__ import annotations

from dataclasses import asdict

from hi_agent.contracts.reasoning_trace import ReasoningTrace, ReasoningTraceEntry


def test_reasoning_trace_entry_has_required_fields():
    """ReasoningTraceEntry must expose all required contract fields."""
    entry = ReasoningTraceEntry(
        run_id="run-001",
        stage_id="reflect",
        step=0,
        kind="thought",
        content="considering the problem",
    )
    assert entry.run_id == "run-001"
    assert entry.stage_id == "reflect"
    assert entry.step == 0
    assert entry.kind == "thought"
    assert entry.content == "considering the problem"
    assert isinstance(entry.metadata, dict)
    assert entry.created_at == ""  # default empty string


def test_reasoning_trace_entry_serializes_to_dict():
    """ReasoningTraceEntry can be converted to a dict and values are preserved."""
    entry = ReasoningTraceEntry(
        run_id="r1",
        stage_id="plan",
        step=1,
        kind="plan",
        content="create a step-by-step plan",
        metadata={"tokens": 42},
        created_at="2026-04-25T00:00:00+00:00",
    )
    d = asdict(entry)
    assert d["run_id"] == "r1"
    assert d["stage_id"] == "plan"
    assert d["step"] == 1
    assert d["kind"] == "plan"
    assert d["content"] == "create a step-by-step plan"
    assert d["metadata"] == {"tokens": 42}
    assert d["created_at"] == "2026-04-25T00:00:00+00:00"


def test_reasoning_trace_entries_is_list():
    """ReasoningTrace.entries defaults to an empty list."""
    trace = ReasoningTrace(run_id="run-002")
    assert trace.run_id == "run-002"
    assert isinstance(trace.entries, list)
    assert trace.entries == []


def test_reasoning_trace_entries_can_be_populated():
    """ReasoningTrace.entries accepts ReasoningTraceEntry instances."""
    entry = ReasoningTraceEntry(
        run_id="run-003",
        stage_id="tool_call",
        step=2,
        kind="tool_call",
        content='{"tool": "search", "query": "foo"}',
    )
    trace = ReasoningTrace(run_id="run-003", entries=[entry])
    assert len(trace.entries) == 1
    assert trace.entries[0].kind == "tool_call"


def test_reasoning_trace_entry_kind_values():
    """All documented kind values are assignable without error."""
    for kind in ("thought", "plan", "reflection", "tool_call", "tool_result"):
        entry = ReasoningTraceEntry(
            run_id="r", stage_id="s", step=0, kind=kind, content=""
        )
        assert entry.kind == kind
