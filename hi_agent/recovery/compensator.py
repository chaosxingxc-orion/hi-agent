"""Failure compensation plan generator."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from hi_agent.events import EventEnvelope


@dataclass(frozen=True, slots=True)
class CompensationPlan:
    """Recovery guidance synthesized from failure events."""

    actions: list[str]
    reason: str
    failed_stages: list[str]


CompensationHandler = Callable[[CompensationPlan, tuple[EventEnvelope, ...]], Any]
"""Callable signature used by compensation action handlers."""


@dataclass(frozen=True, slots=True)
class CompensationExecutionResult:
    """Execution outcome for one planned compensation action.

    Attributes:
        action: Planned action name (for example, ``retry_failed_actions``).
        status: Execution status for the action.
        output: Optional handler output when execution succeeds.
        error: Optional error message when execution fails.
    """

    action: str
    status: Literal["success", "failed", "skipped"]
    output: Any | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CompensationExecutionReport:
    """Aggregate report returned by compensation execution.

    Attributes:
        plan: The compensation plan derived from the provided events.
        results: Per-action execution details in planned order.
        succeeded_actions: Actions that executed successfully.
        failed_actions: Actions with handler failures.
        skipped_actions: Actions skipped due to missing handlers.
        success: ``True`` when no action failed, otherwise ``False``.
    """

    plan: CompensationPlan
    results: list[CompensationExecutionResult]
    succeeded_actions: list[str]
    failed_actions: list[str]
    skipped_actions: list[str]
    success: bool


def build_compensation_plan(events: Iterable[EventEnvelope]) -> CompensationPlan:
    """Build a compensation plan from ordered event envelopes.

    This function is intentionally deterministic and backward compatible with
    existing behavior because other recovery tests rely on exact action and
    reason strings.

    Args:
        events: Ordered event envelopes from one run.

    Returns:
        A normalized compensation plan that captures recommended actions.
    """
    failed_stages: list[str] = []
    failed_stage_set: set[str] = set()
    has_action_failure = False
    has_stage_failure = False

    for envelope in events:
        payload = envelope.payload or {}
        stage_id = payload.get("stage_id")

        if envelope.event_type == "ActionExecutionFailed":
            has_action_failure = True
            if stage_id is not None:
                stage_key = str(stage_id)
                if stage_key not in failed_stage_set:
                    failed_stage_set.add(stage_key)
                    failed_stages.append(stage_key)
            continue

        if envelope.event_type == "StageStateChanged" and str(payload.get("to_state")) == "failed":
            has_stage_failure = True
            if stage_id is not None:
                stage_key = str(stage_id)
                if stage_key not in failed_stage_set:
                    failed_stage_set.add(stage_key)
                    failed_stages.append(stage_key)

    if not has_action_failure and not has_stage_failure:
        return CompensationPlan(
            actions=[],
            reason="no_failures_detected",
            failed_stages=[],
        )

    if has_stage_failure and not has_action_failure:
        return CompensationPlan(
            actions=["escalate_to_human"],
            reason="dead_end_detected",
            failed_stages=failed_stages,
        )

    if has_action_failure and has_stage_failure:
        return CompensationPlan(
            actions=[
                "retry_failed_actions",
                "replan_from_failed_stages",
                "escalate_to_human",
            ],
            reason="mixed_failures_detected",
            failed_stages=failed_stages,
        )

    return CompensationPlan(
        actions=["retry_failed_actions", "replan_from_failed_stages"],
        reason="action_execution_failed",
        failed_stages=failed_stages,
    )


def execute_compensation(
    events: Iterable[EventEnvelope],
    handlers: Mapping[str, CompensationHandler] | None = None,
) -> CompensationExecutionReport:
    """Execute compensation actions against registered handlers.

    The function first builds a plan from the provided events, then executes
    each planned action in order. Missing handlers are treated as safe no-op
    skips so callers can roll out execution progressively.

    Args:
        events: Ordered event envelopes used for planning and execution context.
        handlers: Optional action-to-handler mapping. Unknown or missing actions
            are skipped safely.

    Returns:
        A detailed execution report with per-action outcomes and overall status.
    """
    consumed_events = tuple(events)
    plan = build_compensation_plan(consumed_events)
    registered_handlers = handlers or {}

    results: list[CompensationExecutionResult] = []
    succeeded_actions: list[str] = []
    failed_actions: list[str] = []
    skipped_actions: list[str] = []

    for action in plan.actions:
        handler = registered_handlers.get(action)
        if handler is None:
            skipped_actions.append(action)
            results.append(
                CompensationExecutionResult(
                    action=action,
                    status="skipped",
                )
            )
            continue

        try:
            output = handler(plan, consumed_events)
        except Exception as exc:
            failed_actions.append(action)
            results.append(
                CompensationExecutionResult(
                    action=action,
                    status="failed",
                    error=str(exc),
                )
            )
            continue

        succeeded_actions.append(action)
        results.append(
            CompensationExecutionResult(
                action=action,
                status="success",
                output=output,
            )
        )

    return CompensationExecutionReport(
        plan=plan,
        results=results,
        succeeded_actions=succeeded_actions,
        failed_actions=failed_actions,
        skipped_actions=skipped_actions,
        success=not failed_actions,
    )
