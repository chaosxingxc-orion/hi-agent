"""Tests for G-7: POST /runs/{id}/gate_decision with approve/backtrack/remediate/escalate."""
import pytest


def test_gate_decision_model_validation():
    """GateDecisionRequest must reject invalid decision values."""
    from pydantic import ValidationError
    try:
        from hi_agent.server.routes_runs import GateDecisionRequest
    except ImportError:
        pytest.skip("GateDecisionRequest not yet defined")
    with pytest.raises(ValidationError):
        GateDecisionRequest(decision="invalid_decision", approver_id="user-1")


def test_gate_decision_request_valid_approve():
    from hi_agent.server.routes_runs import GateDecisionRequest
    req = GateDecisionRequest(decision="approve", approver_id="user-123", note="LGTM")
    assert req.decision == "approve"
    assert req.approver_id == "user-123"
    assert req.note == "LGTM"


def test_gate_decision_request_valid_backtrack():
    from hi_agent.server.routes_runs import GateDecisionRequest
    req = GateDecisionRequest(decision="backtrack", target_phase="proposal", approver_id="u1")
    assert req.decision == "backtrack"
    assert req.target_phase == "proposal"


def test_gate_decision_request_valid_remediate():
    from hi_agent.server.routes_runs import GateDecisionRequest
    req = GateDecisionRequest(decision="remediate", approver_id="u1", remediation={"key": "val"})
    assert req.decision == "remediate"
    assert req.remediation == {"key": "val"}


def test_gate_decision_request_valid_escalate():
    from hi_agent.server.routes_runs import GateDecisionRequest
    req = GateDecisionRequest(decision="escalate", approver_id="u1")
    assert req.decision == "escalate"


def test_gate_decision_request_defaults():
    from hi_agent.server.routes_runs import GateDecisionRequest
    req = GateDecisionRequest(decision="approve", approver_id="u1")
    assert req.target_phase == ""
    assert req.remediation == {}
    assert req.note == ""


def test_gate_coordinator_apply_decision_returns_event_id():
    """GateCoordinator.apply_decision() returns a dict with event_id."""
    from hi_agent.execution.gate_coordinator import GateCoordinator
    from unittest.mock import MagicMock
    coord = GateCoordinator(executor=MagicMock())
    result = coord.apply_decision(
        run_id="run-1",
        decision="approve",
        approver_id="user-123",
    )
    assert "event_id" in result
    assert result["event_id"]  # non-empty


def test_gate_coordinator_apply_decision_backtrack():
    from hi_agent.execution.gate_coordinator import GateCoordinator
    from unittest.mock import MagicMock
    coord = GateCoordinator(executor=MagicMock())
    result = coord.apply_decision(
        run_id="run-1",
        decision="backtrack",
        target_phase="proposal",
        approver_id="user-1",
    )
    assert "event_id" in result


def test_gate_coordinator_apply_decision_remediate():
    from hi_agent.execution.gate_coordinator import GateCoordinator
    from unittest.mock import MagicMock
    coord = GateCoordinator(executor=MagicMock())
    result = coord.apply_decision(
        run_id="run-1",
        decision="remediate",
        remediation={"retry": True},
        approver_id="user-1",
    )
    assert "event_id" in result
