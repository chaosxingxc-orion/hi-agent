"""Tests for centralized run state machine transitions.

Profile validated: default-offline
"""
from __future__ import annotations

import pytest
from hi_agent.server.run_state_transitions import is_terminal, transition


class FakeRun:
    """Minimal run-like object for testing — no external dependencies."""

    def __init__(self, state: str, run_id: str = "test-run-001") -> None:
        self.state = state
        self.run_id = run_id


# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------


def test_legal_transition_created_to_running():
    run = FakeRun("created")
    transition(run, "running", reason="worker claimed run")
    assert run.state == "running"


def test_legal_transition_running_to_completed():
    run = FakeRun("running")
    transition(run, "completed", reason="executor returned success")
    assert run.state == "completed"


def test_legal_transition_running_to_failed():
    run = FakeRun("running")
    transition(run, "failed", reason="executor raised exception")
    assert run.state == "failed"


def test_legal_transition_running_to_cancelled():
    run = FakeRun("running")
    transition(run, "cancelled", reason="cancel requested")
    assert run.state == "cancelled"


def test_legal_transition_created_to_failed():
    run = FakeRun("created")
    transition(run, "failed", reason="queue_timeout")
    assert run.state == "failed"


def test_legal_transition_created_to_cancelled():
    run = FakeRun("created")
    transition(run, "cancelled", reason="cancel before dispatch")
    assert run.state == "cancelled"


# ---------------------------------------------------------------------------
# Illegal transitions — must raise ValueError
# ---------------------------------------------------------------------------


def test_illegal_transition_completed_to_running_raises():
    run = FakeRun("completed")
    with pytest.raises(ValueError, match="Illegal state transition"):
        transition(run, "running")


def test_terminal_to_terminal_is_noop_race(caplog):
    """Terminal-to-terminal transitions are no-ops (cancellation race).

    When the executor's natural completion races with an external cancel
    (Rule 8 step 6 cancellation round-trip), the second transition attempt
    must not raise — terminal states are sticky, but the race is logged at
    WARNING for operator attribution.
    """
    import logging
    run = FakeRun("failed")
    with caplog.at_level(logging.WARNING, logger="hi_agent.server.run_state_transitions"):
        transition(run, "completed")  # must not raise
    assert run.state == "failed"
    assert any("terminal_race" in r.getMessage() for r in caplog.records)


def test_illegal_transition_cancelled_to_running_raises():
    run = FakeRun("cancelled")
    with pytest.raises(ValueError, match="Illegal state transition"):
        transition(run, "running")


# ---------------------------------------------------------------------------
# Idempotency — same-state transition must be a no-op, not an error
# ---------------------------------------------------------------------------


def test_idempotent_same_state_running_is_noop():
    run = FakeRun("running")
    transition(run, "running")  # must not raise
    assert run.state == "running"


def test_idempotent_same_state_completed_is_noop():
    run = FakeRun("completed")
    transition(run, "completed")  # must not raise
    assert run.state == "completed"


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------


def test_is_terminal_completed():
    assert is_terminal("completed") is True


def test_is_terminal_failed():
    assert is_terminal("failed") is True


def test_is_terminal_cancelled():
    assert is_terminal("cancelled") is True


def test_is_terminal_running():
    assert is_terminal("running") is False


def test_is_terminal_created():
    assert is_terminal("created") is False


# ---------------------------------------------------------------------------
# Unknown current state
# ---------------------------------------------------------------------------


def test_unknown_current_state_raises():
    run = FakeRun("invalid_state")
    with pytest.raises(ValueError, match="Unknown current state"):
        transition(run, "completed")


# ---------------------------------------------------------------------------
# reason / idempotent_token do not affect transition outcome
# ---------------------------------------------------------------------------


def test_transition_accepts_reason_kwarg():
    run = FakeRun("created")
    transition(run, "running", reason="test", idempotent_token="tok-123")
    assert run.state == "running"
