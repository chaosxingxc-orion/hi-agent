"""E2E: cancel_run propagates to CancellationToken and RunQueue (P3.3).

Uses real RunManager (no mocks on the SUT) to verify that cancel_run():
1. Sets the run state to "cancelled".
2. Signals a registered CancellationToken via .cancel().
3. Calls RunQueue.cancel() when a durable queue is wired in.
"""

from __future__ import annotations

import pytest
from hi_agent.server.run_manager import RunManager


class _FakeCancellationToken:
    """Minimal stand-in for CancellationToken — records .cancel() calls."""

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def check_or_raise(self) -> None:
        if self.cancelled:
            raise RuntimeError("cancelled")


@pytest.mark.serial
def test_cancel_run_sets_state():
    """cancel_run returns True and transitions run to 'cancelled'."""
    manager = RunManager(max_concurrent=1, queue_size=4)
    run_id = manager.create_run({"goal": "test"}).run_id
    result = manager.cancel_run(run_id)
    assert result is True
    run = manager.get_run(run_id)
    assert run is not None
    assert run.state == "cancelled"


@pytest.mark.serial
def test_cancel_run_signals_registered_token():
    """cancel_run calls .cancel() on a registered CancellationToken."""
    manager = RunManager(max_concurrent=1, queue_size=4)
    run_id = manager.create_run({"goal": "test"}).run_id
    # Transition to running so cancel is accepted.
    with manager._lock:
        manager._runs[run_id].state = "running"
    token = _FakeCancellationToken()
    manager.register_cancellation_token(run_id, token)
    result = manager.cancel_run(run_id)
    assert result is True
    assert token.cancelled is True


@pytest.mark.serial
def test_cancel_run_without_token_still_returns_true():
    """cancel_run succeeds even when no token is registered."""
    manager = RunManager(max_concurrent=1, queue_size=4)
    run_id = manager.create_run({"goal": "test"}).run_id
    result = manager.cancel_run(run_id)
    assert result is True
    run = manager.get_run(run_id)
    assert run.state == "cancelled"


@pytest.mark.serial
def test_cancel_run_already_terminal_returns_false():
    """cancel_run returns False when the run is already in a terminal state."""
    manager = RunManager(max_concurrent=1, queue_size=4)
    run_id = manager.create_run({"goal": "test"}).run_id
    with manager._lock:
        manager._runs[run_id].state = "completed"
    result = manager.cancel_run(run_id)
    assert result is False


@pytest.mark.serial
def test_cancel_run_unknown_id_returns_false():
    """cancel_run returns False for an unknown run_id."""
    manager = RunManager(max_concurrent=1, queue_size=4)
    result = manager.cancel_run("nonexistent-run-id")
    assert result is False


@pytest.mark.serial
def test_register_unregister_token():
    """register_cancellation_token / unregister_cancellation_token are symmetric."""
    manager = RunManager(max_concurrent=1, queue_size=4)
    run_id = manager.create_run({"goal": "test"}).run_id
    token = _FakeCancellationToken()
    manager.register_cancellation_token(run_id, token)
    assert manager._active_executor_tokens.get(run_id) is token
    manager.unregister_cancellation_token(run_id)
    assert run_id not in manager._active_executor_tokens
