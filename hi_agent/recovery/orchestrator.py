"""Recovery orchestration helpers for runner-facing integration."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from hi_agent.events import EventEnvelope
from hi_agent.recovery.compensator import (
    CompensationExecutionReport,
    CompensationHandler,
    execute_compensation,
)

ActionStatus = Literal["success", "failed", "skipped"]
"""Normalized action status values returned by compensation execution."""


@dataclass(frozen=True, slots=True)
class RecoveryOrchestrationResult:
    """Structured recovery summary for runner-level decision points.

    Attributes:
        execution_report: Full underlying compensation execution report.
        should_escalate: ``True`` when the runner should escalate to human
            intervention (escalation action unresolved or any action failed).
        failed_stages: Ordered failed stage identifiers from the plan.
        action_status_map: Planned action to execution status mapping.
    """

    execution_report: CompensationExecutionReport
    should_escalate: bool
    failed_stages: list[str]
    action_status_map: dict[str, ActionStatus]


def orchestrate_recovery(
    events: Iterable[EventEnvelope],
    handlers: Mapping[str, CompensationHandler] | None = None,
) -> RecoveryOrchestrationResult:
    """Execute recovery compensation and produce a runner-friendly summary.

    This API is intentionally thin and is built directly around
    :func:`execute_compensation` to preserve existing compensation behavior.

    Args:
        events: Ordered event envelopes from one run.
        handlers: Optional action-to-handler mapping for compensation actions.

    Returns:
        Structured summary with escalation signal, failed stages, and per-action
        execution statuses suitable for runner integration.
    """
    report = execute_compensation(events, handlers=handlers)
    action_status_map = {result.action: result.status for result in report.results}

    # Escalation is required when planned escalation did not complete or any
    # compensation action failed and needs manual intervention.
    should_escalate = (
        "escalate_to_human" in report.plan.actions
        and action_status_map.get("escalate_to_human") != "success"
    ) or bool(report.failed_actions)

    return RecoveryOrchestrationResult(
        execution_report=report,
        should_escalate=should_escalate,
        failed_stages=list(report.plan.failed_stages),
        action_status_map=action_status_map,
    )
