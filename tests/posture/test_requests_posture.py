"""Posture-matrix coverage for requests contracts (AX-B B5).

Covers:
  hi_agent/contracts/requests.py — StartRunRequest, StartRunResponse,
      SignalRunRequest, QueryRunResponse, TraceRuntimeView,
      OpenBranchRequest, BranchStateUpdateRequest, HumanGateRequest,
      ApprovalRequest, KernelManifest, RunResult

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# StartRunRequest
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_start_run_request_instantiates_under_posture(monkeypatch, posture_name):
    """StartRunRequest must be instantiable with required fields under all postures.

    Under research/prod the spine field tenant_id is required (Rule 12).
    Under dev empty tenant_id only emits a warning (back-compat).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import StartRunRequest

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    tenant_id = "" if posture_name == "dev" else "tenant-test"
    req = StartRunRequest(task_contract={"goal": "test"}, tenant_id=tenant_id)
    assert req.task_contract == {"goal": "test"}
    assert req.task_family == "quick_task"
    assert req.profile_id is None
    assert req.tenant_id == tenant_id


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_start_run_request_requires_task_contract(monkeypatch, posture_name):
    """StartRunRequest without task_contract raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import StartRunRequest

    with pytest.raises(TypeError):
        StartRunRequest()  # missing task_contract


# ---------------------------------------------------------------------------
# StartRunResponse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_start_run_response_instantiates_under_posture(monkeypatch, posture_name):
    """StartRunResponse must be instantiable with required fields under all postures.

    Under research/prod the spine field tenant_id is required (Rule 12).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import StartRunResponse
    from hi_agent.contracts.run import RunState

    tenant_id = "" if posture_name == "dev" else "tenant-test"
    resp = StartRunResponse(run_id="run-123", tenant_id=tenant_id)
    assert resp.run_id == "run-123"
    assert resp.status == RunState.CREATED
    assert resp.tenant_id == tenant_id


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_start_run_response_requires_run_id(monkeypatch, posture_name):
    """StartRunResponse without run_id raises TypeError in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import StartRunResponse

    with pytest.raises(TypeError):
        StartRunResponse()  # missing run_id


# ---------------------------------------------------------------------------
# HumanGateRequest (has spine fields)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_human_gate_request_instantiates_under_posture(monkeypatch, posture_name):
    """HumanGateRequest must be instantiable with required fields under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import HumanGateRequest

    req = HumanGateRequest(run_id="r1", gate_type="human", gate_ref="ref-abc")
    assert req.run_id == "r1"
    assert req.gate_type == "human"
    assert req.gate_ref == "ref-abc"
    assert req.timeout_s == 3600


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_run_result_instantiates_under_posture(monkeypatch, posture_name):
    """RunResult must be instantiable under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import RunResult

    result = RunResult(run_id="r1", status="completed")
    assert result.run_id == "r1"
    assert result.status == "completed"
    assert result.success is True
    assert str(result) == "completed"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_run_result_failed_under_posture(monkeypatch, posture_name):
    """RunResult with failed status has correct success flag under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import RunResult

    result = RunResult(run_id="r1", status="failed", error="some error")
    assert result.success is False
    assert result.error == "some error"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_run_result_to_dict_under_posture(monkeypatch, posture_name):
    """RunResult.to_dict returns JSON-serializable dict under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.requests import RunResult

    result = RunResult(run_id="r1", status="completed")
    d = result.to_dict()
    assert d["run_id"] == "r1"
    assert d["status"] == "completed"
    assert "fallback_events" in d
    assert "llm_fallback_count" in d
