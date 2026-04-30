"""Posture-matrix coverage for execution_provenance contracts (AX-B B5).

Covers:
  hi_agent/contracts/execution_provenance.py — StageProvenance,
      ExecutionProvenance

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# StageProvenance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_provenance_instantiates_under_posture(monkeypatch, posture_name):
    """StageProvenance must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.execution_provenance import StageProvenance

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    prov = StageProvenance(
        stage_id="s1",
        llm_mode="real",
        capability_mode="profile",
        fallback_used=False,
        fallback_reasons=[],
        duration_ms=100,
    )
    assert prov.stage_id == "s1"
    assert prov.llm_mode == "real"
    assert prov.fallback_used is False
    assert prov.fallback_reasons == []


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_provenance_requires_all_fields(monkeypatch, posture_name):
    """StageProvenance without required fields raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.execution_provenance import StageProvenance

    with pytest.raises(TypeError):
        StageProvenance()  # missing stage_id, llm_mode, capability_mode, etc.


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_provenance_deduplicates_fallback_reasons(monkeypatch, posture_name):
    """StageProvenance deduplicates and sorts fallback_reasons under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.execution_provenance import StageProvenance

    prov = StageProvenance(
        stage_id="s1",
        llm_mode="heuristic",
        capability_mode="sample",
        fallback_used=True,
        fallback_reasons=["b", "a", "b"],
        duration_ms=50,
    )
    assert prov.fallback_reasons == ["a", "b"]


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_stage_provenance_to_dict_under_posture(monkeypatch, posture_name):
    """StageProvenance.to_dict returns complete dict under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.execution_provenance import StageProvenance

    prov = StageProvenance(
        stage_id="s1",
        llm_mode="real",
        capability_mode="mcp",
        fallback_used=False,
        fallback_reasons=[],
        duration_ms=200,
    )
    d = prov.to_dict()
    assert d["stage_id"] == "s1"
    assert d["llm_mode"] == "real"
    assert d["capability_mode"] == "mcp"


# ---------------------------------------------------------------------------
# ExecutionProvenance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_execution_provenance_instantiates_under_posture(monkeypatch, posture_name):
    """ExecutionProvenance must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.execution_provenance import ExecutionProvenance

    prov = ExecutionProvenance(
        contract_version="2026-04-17",
        runtime_mode="dev-smoke",
        llm_mode="heuristic",
        kernel_mode="local-fsm",
        capability_mode="sample",
        mcp_transport="not_wired",
        fallback_used=True,
        fallback_reasons=["heuristic_stages_present"],
        evidence={"heuristic_stage_count": 2},
    )
    assert prov.contract_version == "2026-04-17"
    assert prov.fallback_used is True


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_execution_provenance_build_from_stages_under_posture(monkeypatch, posture_name):
    """ExecutionProvenance.build_from_stages works under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.execution_provenance import ExecutionProvenance, StageProvenance

    stage_summaries = [
        {
            "provenance": StageProvenance(
                stage_id="s1",
                llm_mode="real",
                capability_mode="profile",
                fallback_used=False,
                fallback_reasons=[],
                duration_ms=100,
            )
        }
    ]
    runtime_context = {"runtime_mode": "local-real", "mcp_transport": "not_wired"}
    prov = ExecutionProvenance.build_from_stages(stage_summaries, runtime_context)
    assert prov.llm_mode == "real"
    assert prov.runtime_mode == "local-real"
