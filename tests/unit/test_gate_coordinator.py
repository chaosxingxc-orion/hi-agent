from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from hi_agent.execution.gate_coordinator import GateCoordinator


def _executor() -> MagicMock:
    executor = MagicMock()
    executor.run_id = "run-gate"
    executor.current_stage = "stage-a"
    executor.session = SimpleNamespace(events=[], stage_states={})
    executor.kernel = MagicMock()
    executor._emit_observability = MagicMock()
    executor._log_best_effort_exception = MagicMock()
    executor._execute_remaining = MagicMock(return_value="completed")
    executor._finalize_run = MagicMock(return_value="failed")
    executor.stage_summaries = {}
    return executor


def test_register_gate_sets_pending() -> None:
    executor = _executor()
    coordinator = GateCoordinator(executor)

    coordinator.register_gate(
        "gate-1",
        gate_type="artifact_review",
        phase_name="stage-a",
        recommendation="approve",
        output_summary="summary",
    )

    assert coordinator.gate_pending == "gate-1"
    assert coordinator.registered_gates["gate-1"].gate_type == "artifact_review"
    assert executor.session.events[-1]["event"] == "gate_registered"


def test_resume_clears_pending() -> None:
    executor = _executor()
    coordinator = GateCoordinator(executor)
    coordinator.register_gate("gate-1")

    coordinator.resume("gate-1", "approved", "looks good")

    assert coordinator.gate_pending is None
    executor._emit_observability.assert_called_once_with(
        "gate_decision",
        {
            "run_id": "run-gate",
            "gate_id": "gate-1",
            "decision": "approved",
            "rationale": "looks good",
        },
    )
    assert executor.session.events[-1] == {
        "event": "gate_decision",
        "gate_id": "gate-1",
        "decision": "approved",
        "rationale": "looks good",
    }


def test_continue_from_gate_calls_execute_remaining() -> None:
    executor = _executor()
    coordinator = GateCoordinator(executor)
    coordinator.register_gate("gate-1")

    result = coordinator.continue_from_gate("gate-1", "approved")

    assert result == "completed"
    executor._execute_remaining.assert_called_once_with()
    assert coordinator.gate_pending is None


def test_backtrack_calls_finalize_failed() -> None:
    executor = _executor()
    coordinator = GateCoordinator(executor)
    coordinator.register_gate("gate-1")

    result = coordinator.continue_from_gate_graph("gate-1", "backtrack")

    assert result == "failed"
    executor._finalize_run.assert_called_once_with("failed")
    assert executor._run_terminated is True


def test_registered_gates_property() -> None:
    coordinator = GateCoordinator(_executor())

    coordinator.register_gate("gate-1")

    assert "gate-1" in coordinator.registered_gates
    assert coordinator.registered_gates is coordinator.registered_gates


def test_gate_pending_property() -> None:
    coordinator = GateCoordinator(_executor())

    assert coordinator.gate_pending is None

    coordinator.register_gate("gate-1")

    assert coordinator.gate_pending == "gate-1"

