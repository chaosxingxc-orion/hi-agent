"""State machine transition coverage (AX-B B4).

Validates that every RunState value used in a documented transition is
a member of the RunState enum.  One test per transition direction.

This is a Layer 1/2 contract test: it does NOT drive HTTP — it asserts
that the state vocabulary is internally consistent so higher-level tests
(Layer 3) can rely on known state names.

Profile validated: default-offline
"""
from __future__ import annotations

import pytest

# Documented state transitions:
#   (source_state, target_state, scenario_label)
# Source: RunState docstring in hi_agent/contracts/run.py
# Formal TRACE states: CREATED → ACTIVE → COMPLETED/FAILED/ABORTED
# Operational states: RUNNING, CANCELLED, QUEUE_TIMEOUT, QUEUE_FULL
TRANSITIONS = [
    # CREATED originates a run
    ("CREATED", "ACTIVE", "start_run"),
    ("CREATED", "ABORTED", "abort_before_start"),
    ("CREATED", "RUNNING", "worker_picks_up"),
    # ACTIVE is the main execution state
    ("ACTIVE", "WAITING", "gate_pause"),
    ("ACTIVE", "COMPLETED", "happy_path"),
    ("ACTIVE", "FAILED", "error_in_run"),
    ("ACTIVE", "ABORTED", "abort_active"),
    ("ACTIVE", "RECOVERING", "crash_during_active"),
    # WAITING (gate / human approval hold)
    ("WAITING", "ACTIVE", "gate_resume"),
    ("WAITING", "CANCELLED", "cancel_while_waiting"),
    ("WAITING", "RECOVERING", "crash_while_waiting"),
    # RECOVERING (lease-expired re-enqueue)
    ("RECOVERING", "ACTIVE", "recovery_succeeds"),
    ("RECOVERING", "FAILED", "recovery_exhausted"),
    # RUNNING (server operational)
    ("RUNNING", "COMPLETED", "worker_done"),
    ("RUNNING", "FAILED", "worker_error"),
    ("RUNNING", "ABORTED", "abort_running"),
    ("RUNNING", "CANCELLED", "cancel_running"),
    ("RUNNING", "QUEUE_TIMEOUT", "queue_timeout"),
    # Queue-pressure operational states
    ("CREATED", "QUEUE_FULL", "queue_full_rejection"),
    ("CREATED", "QUEUE_TIMEOUT", "queue_timeout_at_submit"),
]


@pytest.mark.parametrize(
    "from_state,to_state,scenario",
    TRANSITIONS,
    ids=[f"{f}->{t}:{s}" for f, t, s in TRANSITIONS],
)
def test_state_transition_states_exist(from_state: str, to_state: str, scenario: str) -> None:
    """Both source and target state must be valid RunState enum members.

    Verifies the transition vocabulary is coherent without requiring a
    running server or triggering real lifecycle events.
    """
    try:
        from hi_agent.contracts.run import RunState
    except ImportError:
        pytest.skip(reason="hi_agent.contracts.run not importable")

    valid_values = {s.value for s in RunState}
    valid_names = {s.name for s in RunState}

    def _member_exists(state_str: str) -> bool:
        return state_str in valid_names or state_str.lower() in valid_values

    assert _member_exists(from_state), (
        f"Transition source '{from_state}' (scenario={scenario}) is not a "
        f"member of RunState. Valid names: {sorted(valid_names)}"
    )
    assert _member_exists(to_state), (
        f"Transition target '{to_state}' (scenario={scenario}) is not a "
        f"member of RunState. Valid names: {sorted(valid_names)}"
    )
