"""Unit tests for recovery pre-condition guard and exception context in _trigger_recovery."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.execution.recovery_coordinator import RecoveryContext
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter import RuntimeAdapter


@pytest.fixture
def mock_kernel() -> MagicMock:
    """Create a mock kernel adapter."""
    kernel = MagicMock(spec=RuntimeAdapter)
    kernel.start_run.return_value = "run-test-123"
    return kernel


@pytest.fixture
def base_contract() -> TaskContract:
    """Create a base task contract."""
    return TaskContract(task_id="test-task", goal="Test recovery guard")


def test_trigger_recovery_no_handlers_logs_warning_and_continues(
    mock_kernel: MagicMock, base_contract: TaskContract
) -> None:
    """Test that _trigger_recovery with no recovery_handlers logs warning but continues."""
    executor = RunExecutor(
        contract=base_contract,
        kernel=mock_kernel,
        recovery_handlers=None,
    )
    executor._run_id = "run-test-123"

    # Mock _build_recovery_context to avoid full setup
    mock_ctx = MagicMock(spec=RecoveryContext)
    with (
        patch.object(executor, "_build_recovery_context", return_value=mock_ctx),
        patch("hi_agent.runner.RecoveryCoordinator") as mock_rc,
    ):
        executor._trigger_recovery("stage-1")

        # Verify RecoveryCoordinator was still called (not skipped)
        mock_rc.assert_called_once_with(mock_ctx)
        mock_rc.return_value._trigger_recovery.assert_called_once_with("stage-1")


def test_trigger_recovery_no_handlers_with_caplog(
    mock_kernel: MagicMock, base_contract: TaskContract, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that _trigger_recovery logs a warning when recovery_handlers is None."""
    executor = RunExecutor(
        contract=base_contract,
        kernel=mock_kernel,
        recovery_handlers=None,
    )
    executor._run_id = "run-test-123"

    # Capture logging output
    with caplog.at_level(logging.WARNING):
        executor._trigger_recovery("stage-1")

    # Should complete without error
    assert True


def test_trigger_recovery_with_handlers_proceeds(
    mock_kernel: MagicMock, base_contract: TaskContract
) -> None:
    """Test that _trigger_recovery with handlers configured proceeds to RecoveryCoordinator."""
    handlers = {"retry_failed_actions": MagicMock()}
    executor = RunExecutor(
        contract=base_contract,
        kernel=mock_kernel,
        recovery_handlers=handlers,
    )
    executor._run_id = "run-test-123"

    # Mock the _build_recovery_context to avoid needing full setup
    mock_ctx = MagicMock(spec=RecoveryContext)
    with (
        patch.object(executor, "_build_recovery_context", return_value=mock_ctx),
        patch("hi_agent.runner.RecoveryCoordinator") as mock_rc,
    ):
        executor._trigger_recovery("stage-1")

        # Verify RecoveryCoordinator was instantiated and _trigger_recovery called
        mock_rc.assert_called_once_with(mock_ctx)
        mock_rc.return_value._trigger_recovery.assert_called_once_with("stage-1")


def test_trigger_recovery_build_context_exception_wrapping(
    mock_kernel: MagicMock, base_contract: TaskContract
) -> None:
    """Test that exception in _build_recovery_context is wrapped with stage_id context."""
    handlers = {"retry_failed_actions": MagicMock()}
    executor = RunExecutor(
        contract=base_contract,
        kernel=mock_kernel,
        recovery_handlers=handlers,
    )
    executor._run_id = "run-test-123"

    # Mock _build_recovery_context to raise an exception
    original_exc = ValueError("test build error")
    with patch.object(
        executor, "_build_recovery_context", side_effect=original_exc
    ):
        with pytest.raises(RuntimeError) as exc_info:
            executor._trigger_recovery("stage-42")

        # Verify the exception message includes stage_id
        assert "recovery context build failed for stage 'stage-42'" in str(exc_info.value)
        # Verify it was chained from the original exception
        assert exc_info.value.__cause__ is original_exc
