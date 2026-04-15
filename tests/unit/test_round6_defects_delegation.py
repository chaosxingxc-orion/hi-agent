"""Unit tests for H-6 delegation fix: GatePendingError propagation.

Tests that DelegationManager.delegate() correctly distinguishes a child run
raising GatePendingError (status="gate_pending") from a generic exception
(status="failed"), and that gate_id is preserved in the former case.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hi_agent.gate_protocol import GatePendingError
from hi_agent.task_mgmt.delegation import (
    DelegationConfig,
    DelegationManager,
    DelegationRequest,
)


def _make_manager(spawn_side_effect=None) -> DelegationManager:
    """Return a DelegationManager whose kernel raises *spawn_side_effect* on spawn."""
    kernel = MagicMock()
    kernel.spawn_child_run_async = AsyncMock(side_effect=spawn_side_effect)
    config = DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01)
    return DelegationManager(kernel=kernel, config=config, llm=None)


def _make_request(task_id: str = "t1") -> DelegationRequest:
    return DelegationRequest(goal="test goal", task_id=task_id)


class TestGatePendingErrorPropagation:
    """H-6: child run raises GatePendingError → DelegationResult reflects gate state."""

    @pytest.mark.asyncio
    async def test_gate_pending_error_yields_gate_pending_status(self):
        """
        When _delegate_one raises GatePendingError, delegate() must produce a
        DelegationResult with status="gate_pending" and gate_id matching the error.

        Mock rationale: spawn_child_run_async is an external async kernel call;
        mocking it is the correct way to inject the fault without a live kernel.
        """
        manager = _make_manager(spawn_side_effect=GatePendingError("test-gate"))
        req = _make_request("t1")

        results = await manager.delegate([req], parent_run_id="parent-run-1")

        assert len(results) == 1
        result = results[0]
        assert result.status == "gate_pending", (
            f"Expected 'gate_pending', got {result.status!r}"
        )
        assert result.gate_id == "test-gate", (
            f"Expected gate_id='test-gate', got {result.gate_id!r}"
        )

    @pytest.mark.asyncio
    async def test_generic_exception_yields_failed_status_with_no_gate_id(self):
        """
        When _delegate_one raises a generic ValueError, delegate() must produce a
        DelegationResult with status="failed" and gate_id=None.

        Mock rationale: spawn_child_run_async is an external async kernel call;
        mocking it is the correct way to inject the fault without a live kernel.
        """
        manager = _make_manager(spawn_side_effect=ValueError("normal error"))
        req = _make_request("t2")

        results = await manager.delegate([req], parent_run_id="parent-run-2")

        assert len(results) == 1
        result = results[0]
        assert result.status == "failed", (
            f"Expected 'failed', got {result.status!r}"
        )
        assert result.gate_id is None, (
            f"Expected gate_id=None, got {result.gate_id!r}"
        )
        assert "normal error" in (result.error or ""), (
            f"Expected error to contain 'normal error', got {result.error!r}"
        )
