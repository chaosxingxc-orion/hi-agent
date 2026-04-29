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
