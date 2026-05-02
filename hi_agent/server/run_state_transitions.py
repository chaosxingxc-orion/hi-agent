"""Centralized run state transition validator.

All state changes to a ManagedRun MUST go through transition() rather than
direct attribute assignment. This enforces the legal state graph and provides
a single audit point for state changes.

Legal state graph for ManagedRun.state:
    created  -> running, failed, cancelled
    running  -> completed, failed, cancelled
    completed -> (terminal)
    failed    -> (terminal)
    cancelled -> (terminal)

Idempotent transitions: transitioning to the same state is a no-op.

Note on state vocabulary: ManagedRun uses "completed" (not "done") as the
success terminal state, consistent with RunState.COMPLETED and the run_store
contract.  The RunState enum also defines "active", "waiting", "recovering",
"aborted", "queue_timeout", "queue_full" — these are valid enum values that
may arrive via result_status from the kernel; the transition function accepts
them as target states from "running" because the kernel may report any
RunState on its output.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# Legal transitions for ManagedRun.state.
# {from_state: set_of_allowed_to_states}
_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    # Initial state: a run was created but not yet dispatched to a worker.
    "created": {"running", "failed", "cancelled"},
    # Worker is actively executing the run.
    # Any RunState value may come back via result.status (kernel contract),
    # so "running" accepts the full set of known outcome states.
    "running": {
        "completed",
        "failed",
        "cancelled",
        # Kernel formal states that may appear as result.status:
        "active",
        "waiting",
        "recovering",
        "aborted",
        "queue_timeout",
        "queue_full",
    },
    # Terminal states — no outbound transitions permitted.
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
    # Kernel formal states that may appear as intermediate result.status values;
    # they are legal to receive but no further server-side transitions are
    # currently modelled from them.
    "active": {"completed", "failed", "cancelled"},
    "waiting": {"completed", "failed", "cancelled"},
    "recovering": {"completed", "failed", "cancelled"},
    "aborted": set(),        # terminal (kernel aborted)
    "queue_timeout": set(),  # terminal
    "queue_full": set(),     # terminal
}

_TERMINAL_STATES: frozenset[str] = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "aborted",
        "queue_timeout",
        "queue_full",
    }
)


def transition(
    run: object,
    target_state: str,
    *,
    reason: str = "",
    idempotent_token: str = "",
) -> None:
    """Transition *run* to *target_state*, enforcing the legal state graph.

    This is the single authorised write path for ManagedRun.state.  No other
    site in the codebase may assign directly to ``run.state``.

    Args:
        run: The run record object.  Must have a ``.state`` attribute.
        target_state: The state to transition to.
        reason: Human-readable reason for the transition (logged for audit).
        idempotent_token: Optional token logged alongside the transition.

    Raises:
        ValueError: If the transition is not in the legal state graph.
        AttributeError: If *run* has no ``.state`` attribute.
    """
    current_state = run.state  # type: ignore[attr-defined]  # expiry_wave: Wave 30

    # Idempotent: same-state transition is a no-op — not an error.
    if current_state == target_state:
        _logger.debug(
            "state_transition.noop run_id=%s state=%s reason=%s",
            getattr(run, "run_id", "?"),
            current_state,
            reason,
        )
        return

    # Terminal-to-terminal race: if a run is already in a terminal state and
    # the requested target is also terminal, treat as no-op with a WARNING.
    # Common case: executor's natural completion races with an external cancel
    # (Rule 8 step 6 cancellation round-trip). Terminal-to-non-terminal is
    # still a hard error — that would be true state corruption (un-cancel).
    if current_state in _TERMINAL_STATES and target_state in _TERMINAL_STATES:
        _logger.warning(
            "state_transition.terminal_race run_id=%s current=%s target=%s reason=%s",
            getattr(run, "run_id", "?"),
            current_state,
            target_state,
            reason,
        )
        return

    allowed = _LEGAL_TRANSITIONS.get(current_state)
    if allowed is None:
        raise ValueError(
            f"Unknown current state {current_state!r} for run "
            f"{getattr(run, 'run_id', '?')!r}; legal states: {sorted(_LEGAL_TRANSITIONS)}"
        )

    if target_state not in allowed:
        raise ValueError(
            f"Illegal state transition {current_state!r} -> {target_state!r} "
            f"for run {getattr(run, 'run_id', '?')!r}. "
            f"Allowed from {current_state!r}: {sorted(allowed)}"
        )

    _logger.debug(
        "state_transition run_id=%s %s->%s reason=%s token=%s",
        getattr(run, "run_id", "?"),
        current_state,
        target_state,
        reason,
        idempotent_token,
    )
    run.state = target_state  # type: ignore[attr-defined]  # expiry_wave: Wave 30


def is_terminal(state: str) -> bool:
    """Return True if *state* is a terminal state."""
    return state in _TERMINAL_STATES
