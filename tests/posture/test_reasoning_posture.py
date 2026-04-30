"""Posture-matrix coverage for reasoning contracts (AX-B B5).

Covers:
  hi_agent/contracts/reasoning.py — ReasoningStep, ReasoningTrace

Note: reasoning.py and reasoning_trace.py are separate modules.
reasoning.py has a ReasoningTrace with tenant_id spine field.

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# ReasoningStep
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_step_instantiates_under_posture(monkeypatch, posture_name):
    """ReasoningStep must be instantiable with defaults under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning import ReasoningStep

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    step = ReasoningStep()
    assert step.description == ""
    assert step.step_index == -1
    assert step.evidence_refs == []
    assert step.confidence is None


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_step_with_values_under_posture(monkeypatch, posture_name):
    """ReasoningStep with explicit values is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning import ReasoningStep

    step = ReasoningStep(
        description="Analyze the input",
        step_index=0,
        confidence=0.9,
    )
    assert step.description == "Analyze the input"
    assert step.step_index == 0
    assert step.confidence == 0.9


# ---------------------------------------------------------------------------
# ReasoningTrace (from reasoning.py — has tenant_id)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_instantiates_under_posture(monkeypatch, posture_name):
    """ReasoningTrace must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning import ReasoningTrace

    trace = ReasoningTrace(run_id="r1", stage_id="s1", tenant_id="t-abc")
    assert trace.run_id == "r1"
    assert trace.stage_id == "s1"
    assert trace.tenant_id == "t-abc"
    assert trace.steps == []


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_requires_fields(monkeypatch, posture_name):
    """ReasoningTrace without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning import ReasoningTrace

    with pytest.raises(TypeError):
        ReasoningTrace()  # missing run_id, stage_id, tenant_id


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_append_under_posture(monkeypatch, posture_name):
    """ReasoningTrace.append assigns step_index and stores the step."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning import ReasoningStep, ReasoningTrace

    trace = ReasoningTrace(run_id="r1", stage_id="s1", tenant_id="t-abc")
    step = ReasoningStep(description="step 1")
    trace.append(step)
    assert len(trace.steps) == 1
    assert trace.steps[0].step_index == 0


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_reasoning_trace_to_dict_under_posture(monkeypatch, posture_name):
    """ReasoningTrace.to_dict returns serializable dict under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.reasoning import ReasoningTrace

    trace = ReasoningTrace(run_id="r1", stage_id="s1", tenant_id="t-abc")
    d = trace.to_dict()
    assert d["run_id"] == "r1"
    assert d["stage_id"] == "s1"
    assert "steps" in d
