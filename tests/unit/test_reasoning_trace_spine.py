"""Unit tests: ReasoningTraceEntry / ReasoningTrace spine fields (W2-C.1).

Verifies that the contract spine (tenant_id, user_id, session_id,
project_id) is present, defaults to empty string for back-compat with
already-persisted JSONL files, is settable at construction, and round-trips
through ``dataclasses.asdict``.
"""

from __future__ import annotations

from dataclasses import asdict

from hi_agent.contracts.reasoning_trace import ReasoningTrace, ReasoningTraceEntry


def test_reasoning_trace_entry_has_spine_fields_with_defaults() -> None:
    """Spine fields must default to empty strings to preserve back-compat."""
    entry = ReasoningTraceEntry(
        run_id="r1",
        stage_id="reflect",
        step=0,
        kind="thought",
        content="hello",
    )
    assert entry.tenant_id == ""
    assert entry.user_id == ""
    assert entry.session_id == ""
    assert entry.project_id == ""


def test_reasoning_trace_entry_spine_settable() -> None:
    """All four spine fields must be settable at construction."""
    entry = ReasoningTraceEntry(
        run_id="r1",
        stage_id="plan",
        step=0,
        kind="plan",
        content="x",
        tenant_id="tenant-a",
        user_id="user-b",
        session_id="sess-c",
        project_id="proj-d",
    )
    assert entry.tenant_id == "tenant-a"
    assert entry.user_id == "user-b"
    assert entry.session_id == "sess-c"
    assert entry.project_id == "proj-d"


def test_reasoning_trace_entry_spine_in_asdict() -> None:
    """asdict() must include all four spine fields so JSONL serialization
    preserves them on disk."""
    entry = ReasoningTraceEntry(
        run_id="r1",
        stage_id="plan",
        step=1,
        kind="plan",
        content="step",
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        project_id="p1",
    )
    d = asdict(entry)
    assert d["tenant_id"] == "t1"
    assert d["user_id"] == "u1"
    assert d["session_id"] == "s1"
    assert d["project_id"] == "p1"


def test_reasoning_trace_entry_spine_roundtrip_via_dict() -> None:
    """asdict followed by ReasoningTraceEntry(**d) preserves every field
    including the spine."""
    original = ReasoningTraceEntry(
        run_id="r2",
        stage_id="tool_call",
        step=3,
        kind="tool_call",
        content="call",
        metadata={"x": 1},
        created_at="2026-04-26T00:00:00+00:00",
        tenant_id="tenant-rt",
        user_id="user-rt",
        session_id="sess-rt",
        project_id="proj-rt",
    )
    d = asdict(original)
    restored = ReasoningTraceEntry(**d)
    assert restored == original


def test_reasoning_trace_has_spine_fields_with_defaults() -> None:
    """ReasoningTrace must expose the same spine with empty-string defaults."""
    trace = ReasoningTrace(run_id="r-x")
    assert trace.tenant_id == ""
    assert trace.user_id == ""
    assert trace.session_id == ""
    assert trace.project_id == ""


def test_reasoning_trace_spine_settable() -> None:
    """ReasoningTrace must accept spine values at construction."""
    trace = ReasoningTrace(
        run_id="r-x",
        tenant_id="t",
        user_id="u",
        session_id="s",
        project_id="p",
    )
    assert trace.tenant_id == "t"
    assert trace.user_id == "u"
    assert trace.session_id == "s"
    assert trace.project_id == "p"
