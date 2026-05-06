"""Posture-matrix coverage for reasoning_trace contracts (AX-B B5).

Covers:
  hi_agent/contracts/reasoning_trace.py — ReasoningTraceEntry, ReasoningTrace

Note: reasoning_trace.py is the TE-5 platform trace schema module.
It is distinct from reasoning.py which provides the business-layer contract.

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# ReasoningTraceEntry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_entry_instantiates_under_posture(monkeypatch, posture_name):
    """ReasoningTraceEntry must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    entry = ReasoningTraceEntry(
        run_id="r1",
        stage_id="s1",
        step=0,
        kind="thought",
        content="I need to analyze the data.",
    )
    assert entry.run_id == "r1"
    assert entry.stage_id == "s1"
    assert entry.step == 0
    assert entry.kind == "thought"
    assert entry.content == "I need to analyze the data."
    assert entry.tenant_id == ""


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_entry_requires_required_fields(monkeypatch, posture_name):
    """ReasoningTraceEntry without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    with pytest.raises(TypeError):
        ReasoningTraceEntry()  # missing run_id, stage_id, step, kind, content


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_entry_kind_values_under_posture(monkeypatch, posture_name):
    """ReasoningTraceEntry accepts all documented kind values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    for kind in ("thought", "plan", "reflection", "tool_call", "tool_result"):
        entry = ReasoningTraceEntry(
            run_id="r1", stage_id="s1", step=0, kind=kind, content="content"
        )
        assert entry.kind == kind


# ---------------------------------------------------------------------------
# ReasoningTrace (from reasoning_trace.py — platform trace collection)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_from_trace_module_instantiates_under_posture(
    monkeypatch, posture_name
):
    """reasoning_trace.ReasoningTrace must be instantiable with required fields."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning_trace import ReasoningTrace

    trace = ReasoningTrace(run_id="r1")
    assert trace.run_id == "r1"
    assert trace.entries == []
    assert trace.tenant_id == ""


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_from_trace_module_requires_run_id(monkeypatch, posture_name):
    """reasoning_trace.ReasoningTrace without run_id raises TypeError."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning_trace import ReasoningTrace

    with pytest.raises(TypeError):
        ReasoningTrace()  # missing run_id


# ---------------------------------------------------------------------------
# C-4 hidden-defect class — dev-side warn coverage for posture-aware
# spine validation in hi_agent/contracts/reasoning_trace.py.
#
# Strict-side raises (via SpineCompletenessError) for empty run_id /
# stage_id / kind. The dev-side warn branch was untested prior to W37.
# ---------------------------------------------------------------------------


def test_reasoning_trace_entry_dev_posture_empty_run_id_warns(monkeypatch, caplog):
    """C-4: empty run_id under dev posture warns and constructs (entry)."""
    import logging

    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    caplog.set_level(logging.WARNING, logger="hi_agent.contracts.reasoning_trace")
    entry = ReasoningTraceEntry(
        run_id="",
        stage_id="reflect",
        step=0,
        kind="thought",
        content="missing run_id",
    )
    assert entry.run_id == ""
    assert entry.stage_id == "reflect"
    assert entry.kind == "thought"
    matched = [
        rec for rec in caplog.records
        if "reasoning_trace_entry_spine_incomplete" in rec.message
        and "run_id" in rec.message
    ]
    assert matched, "expected warning naming run_id under dev posture"


def test_reasoning_trace_entry_dev_posture_empty_stage_id_warns(monkeypatch, caplog):
    """C-4: empty stage_id under dev posture warns and constructs (entry)."""
    import logging

    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    caplog.set_level(logging.WARNING, logger="hi_agent.contracts.reasoning_trace")
    entry = ReasoningTraceEntry(
        run_id="run-1",
        stage_id="",
        step=0,
        kind="thought",
        content="missing stage_id",
    )
    assert entry.run_id == "run-1"
    assert entry.stage_id == ""
    matched = [
        rec for rec in caplog.records
        if "reasoning_trace_entry_spine_incomplete" in rec.message
        and "stage_id" in rec.message
    ]
    assert matched, "expected warning naming stage_id under dev posture"


def test_reasoning_trace_entry_dev_posture_empty_kind_warns(monkeypatch, caplog):
    """C-4: empty kind under dev posture warns and constructs (entry).

    ``kind`` is the third entry-shape spine field validated by
    ``ReasoningTraceEntry.__post_init__`` (lines 75-87). The dev-side
    warn branch was untested prior to W37.
    """
    import logging

    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    caplog.set_level(logging.WARNING, logger="hi_agent.contracts.reasoning_trace")
    entry = ReasoningTraceEntry(
        run_id="run-1",
        stage_id="reflect",
        step=0,
        kind="",
        content="missing kind",
    )
    assert entry.run_id == "run-1"
    assert entry.kind == ""
    matched = [
        rec for rec in caplog.records
        if "reasoning_trace_entry_spine_incomplete" in rec.message
        and "kind" in rec.message
    ]
    assert matched, "expected warning naming kind under dev posture"


def test_reasoning_trace_jsonl_dev_posture_empty_run_id_warns(monkeypatch, caplog):
    """C-4: empty run_id under dev posture warns and constructs (JSONL trace).

    Strict-side: ``ReasoningTrace.__post_init__`` (lines 127-140 in
    ``hi_agent/contracts/reasoning_trace.py``) raises
    ``SpineCompletenessError`` when run_id is empty under research/prod.
    Dev-side: emits a WARNING and constructs anyway (JSONL back-compat).
    The dev-side warn branch was untested prior to W37.
    """
    import logging

    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.contracts.reasoning_trace import ReasoningTrace

    caplog.set_level(logging.WARNING, logger="hi_agent.contracts.reasoning_trace")
    trace = ReasoningTrace(run_id="")
    assert trace.run_id == ""
    assert trace.entries == []
    matched = [
        rec for rec in caplog.records
        if "reasoning_trace_legacy_spine_incomplete" in rec.message
    ]
    assert matched, "expected legacy spine warning under dev posture"


def test_reasoning_trace_entry_strict_posture_empty_run_id_raises(monkeypatch):
    """Sanity counter-test: strict posture rejects what dev allows.

    Pairs with the dev-warn tests above to lock the strict/dev split.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    from hi_agent.contracts.reasoning import SpineCompletenessError
    from hi_agent.contracts.reasoning_trace import ReasoningTraceEntry

    with pytest.raises(SpineCompletenessError, match="run_id"):
        ReasoningTraceEntry(
            run_id="",
            stage_id="reflect",
            step=0,
            kind="thought",
            content="missing run_id",
        )


def test_reasoning_trace_jsonl_strict_posture_empty_run_id_raises(monkeypatch):
    """Sanity counter-test: strict posture rejects what dev allows (JSONL)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    from hi_agent.contracts.reasoning import SpineCompletenessError
    from hi_agent.contracts.reasoning_trace import ReasoningTrace

    with pytest.raises(SpineCompletenessError, match="run_id"):
        ReasoningTrace(run_id="")
