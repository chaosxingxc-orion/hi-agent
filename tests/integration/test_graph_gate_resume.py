"""Integration test: RunExecutorFacade routes gate resume via graph topology.

J2-2 regression guard — verifies that when facade.run() is called with
use_graph=True, continue_from_gate() delegates to continue_from_gate_graph()
on the underlying executor (not the linear continue_from_gate()).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from hi_agent.executor_facade import RunExecutorFacade
from hi_agent.gate_protocol import GatePendingError


def _make_facade_with_mock_executor(
    execute_graph_side_effect: Any = None,
    continue_from_gate_graph_return: Any = None,
) -> tuple[RunExecutorFacade, MagicMock]:
    """Build a facade whose _executor is replaced by a MagicMock.

    This lets us verify routing without spinning up a full SystemBuilder.
    Using MagicMock here is legitimate: we are testing the facade's delegation
    logic, not the executor's behaviour — the executor is the external boundary
    being verified separately in test_journeys.py.
    """
    facade = RunExecutorFacade.__new__(RunExecutorFacade)
    facade._last_gate_id = None
    facade._last_execution_mode = "linear"

    mock_contract = MagicMock()
    mock_contract.goal = ""
    facade._contract = mock_contract

    mock_executor = MagicMock()
    if execute_graph_side_effect is not None:
        mock_executor.execute_graph.side_effect = execute_graph_side_effect
    if continue_from_gate_graph_return is not None:
        mock_executor.continue_from_gate_graph.return_value = continue_from_gate_graph_return
    facade._executor = mock_executor
    return facade, mock_executor


def test_run_use_graph_calls_execute_graph() -> None:
    """facade.run(use_graph=True) must call executor.execute_graph(), not execute()."""
    run_result = MagicMock()
    run_result.__str__ = lambda self: "completed"
    run_result.run_id = "r-graph-001"
    run_result.error = None

    facade, mock_exec = _make_facade_with_mock_executor()
    mock_exec.execute_graph.return_value = run_result

    result = facade.run("test goal", use_graph=True)

    mock_exec.execute_graph.assert_called_once()
    mock_exec.execute.assert_not_called()
    assert result.success is True
    assert facade._last_execution_mode == "graph"


def test_run_linear_calls_execute() -> None:
    """facade.run(use_graph=False) must call executor.execute(), not execute_graph()."""
    run_result = MagicMock()
    run_result.__str__ = lambda self: "completed"
    run_result.run_id = "r-linear-001"
    run_result.error = None

    facade, mock_exec = _make_facade_with_mock_executor()
    mock_exec.execute.return_value = run_result

    result = facade.run("test goal", use_graph=False)

    mock_exec.execute.assert_called_once()
    mock_exec.execute_graph.assert_not_called()
    assert result.success is True
    assert facade._last_execution_mode == "linear"


def test_continue_from_gate_after_graph_run_uses_graph_method() -> None:
    """After use_graph=True run, continue_from_gate() must delegate to continue_from_gate_graph().

    J2-2: Before the fix continue_from_gate() always called the linear
    continue_from_gate() on the executor regardless of how run() was called.
    """
    gate_id = "gate-graph-test-001"

    # Step 1: run() with execute_graph raising GatePendingError
    facade, mock_exec = _make_facade_with_mock_executor(
        execute_graph_side_effect=GatePendingError(gate_id=gate_id),
    )

    with pytest.raises(GatePendingError) as exc_info:
        facade.run("test goal", use_graph=True)

    assert exc_info.value.gate_id == gate_id
    assert facade._last_gate_id == gate_id
    assert facade._last_execution_mode == "graph"

    # Step 2: continue_from_gate() must call continue_from_gate_graph()
    resume_result = MagicMock()
    resume_result.__str__ = lambda self: "completed"
    resume_result.run_id = "r-graph-resume-001"
    resume_result.error = None
    mock_exec.continue_from_gate_graph.return_value = resume_result

    result = facade.continue_from_gate(gate_id, "approved")

    mock_exec.continue_from_gate_graph.assert_called_once_with(
        gate_id=gate_id,
        decision="approved",
        rationale="",
    )
    # Linear continue_from_gate must NOT be called
    mock_exec.continue_from_gate.assert_not_called()
    assert result.success is True
    assert result.output == "completed"


def test_continue_from_gate_after_linear_run_uses_linear_method() -> None:
    """After a linear run, continue_from_gate() must use the linear executor method.

    Ensures the existing behaviour is preserved when use_graph=False (default).
    """
    gate_id = "gate-linear-test-001"

    facade, mock_exec = _make_facade_with_mock_executor()
    mock_exec.execute.side_effect = GatePendingError(gate_id=gate_id)

    with pytest.raises(GatePendingError):
        facade.run("test goal")  # default: use_graph=False

    assert facade._last_execution_mode == "linear"

    resume_result = MagicMock()
    resume_result.__str__ = lambda self: "completed"
    resume_result.run_id = "r-linear-resume-001"
    resume_result.error = None
    mock_exec.continue_from_gate.return_value = resume_result

    result = facade.continue_from_gate(gate_id, "approved")

    mock_exec.continue_from_gate.assert_called_once_with(
        gate_id=gate_id,
        decision="approved",
        rationale="",
    )
    mock_exec.continue_from_gate_graph.assert_not_called()
    assert result.success is True
