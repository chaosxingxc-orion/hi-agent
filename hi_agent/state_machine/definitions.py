"""Pre-defined TRACE state machines for all first-class runtime entities."""

from __future__ import annotations

from hi_agent.state_machine.machine import StateMachine


def run_state_machine() -> StateMachine:
    """State machine for a Run lifecycle.

    created -> active -> waiting -> recovering -> completed / failed / aborted
    """
    states = {"created", "active", "waiting", "recovering", "completed", "failed", "aborted", "cancelled"}
    terminal = {"completed", "failed", "aborted", "cancelled"}
    transitions = {
        "created": {"active", "cancelled"},
        "active": {"waiting", "completed", "failed", "aborted", "cancelled"},
        "waiting": {"active", "recovering", "aborted", "cancelled"},
        "recovering": {"active", "failed", "aborted", "cancelled"},
    }
    return StateMachine(
        name="run",
        states=states,
        initial="created",
        transitions=transitions,
        terminal=terminal,
    )


def stage_state_machine() -> StateMachine:
    """State machine for a Stage lifecycle.

    pending -> active -> blocked -> completed / failed
    """
    states = {"pending", "active", "blocked", "completed", "failed"}
    terminal = {"completed", "failed"}
    transitions = {
        "pending": {"active"},
        "active": {"blocked", "completed", "failed"},
        "blocked": {"active", "failed"},
    }
    return StateMachine(
        name="stage",
        states=states,
        initial="pending",
        transitions=transitions,
        terminal=terminal,
    )


def branch_state_machine() -> StateMachine:
    """State machine for a Branch lifecycle.

    proposed -> active -> pruned / waiting / succeeded / failed
    """
    states = {"proposed", "active", "pruned", "waiting", "succeeded", "failed"}
    terminal = {"pruned", "succeeded", "failed"}
    transitions = {
        "proposed": {"active", "pruned"},
        "active": {"pruned", "waiting", "succeeded", "failed"},
        "waiting": {"active", "pruned"},
    }
    return StateMachine(
        name="branch",
        states=states,
        initial="proposed",
        transitions=transitions,
        terminal=terminal,
    )


def action_state_machine() -> StateMachine:
    """State machine for an Action lifecycle.

    prepared -> dispatched -> acknowledged -> succeeded / effect_unknown / failed / compensated
    """
    states = {
        "prepared", "dispatched", "acknowledged",
        "succeeded", "effect_unknown", "failed", "compensated",
    }
    terminal = {"succeeded", "effect_unknown", "failed", "compensated"}
    transitions = {
        "prepared": {"dispatched"},
        "dispatched": {"acknowledged", "failed", "effect_unknown"},
        "acknowledged": {"succeeded", "failed", "effect_unknown", "compensated"},
    }
    return StateMachine(
        name="action",
        states=states,
        initial="prepared",
        transitions=transitions,
        terminal=terminal,
    )


def wait_state_machine() -> StateMachine:
    """State machine for wait/resume semantics.

    none -> external_callback / human_review / scheduled_resume (each back to none)
    """
    states = {"none", "external_callback", "human_review", "scheduled_resume"}
    transitions = {
        "none": {"external_callback", "human_review", "scheduled_resume"},
        "external_callback": {"none"},
        "human_review": {"none"},
        "scheduled_resume": {"none"},
    }
    return StateMachine(
        name="wait",
        states=states,
        initial="none",
        transitions=transitions,
    )


def review_state_machine() -> StateMachine:
    """State machine for artifact review.

    not_required -> requested -> in_review -> approved / rejected
    """
    states = {"not_required", "requested", "in_review", "approved", "rejected"}
    terminal = {"approved", "rejected"}
    transitions = {
        "not_required": {"requested"},
        "requested": {"in_review"},
        "in_review": {"approved", "rejected"},
    }
    return StateMachine(
        name="review",
        states=states,
        initial="not_required",
        transitions=transitions,
        terminal=terminal,
    )
