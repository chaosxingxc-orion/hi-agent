"""Integration tests for recovery orchestration summary API."""

from hi_agent.events import EventEnvelope
from hi_agent.recovery import orchestrate_recovery


def _evt(event_type: str, payload: dict) -> EventEnvelope:
    """Build deterministic test event envelopes."""
    return EventEnvelope(
        event_type=event_type,
        run_id="run-orch-1",
        payload=payload,
        timestamp="2026-04-05T00:00:00+00:00",
    )


def test_orchestrate_recovery_summarizes_execution_statuses() -> None:
    """Orchestrator should expose actionable status summary for runner integration."""
    events = [
        _evt("ActionExecutionFailed", {"stage_id": "S2", "action_kind": "fetch_docs"}),
        _evt("StageStateChanged", {"stage_id": "S2", "to_state": "failed"}),
    ]

    def _retry(*_: object) -> str:
        return "retried"

    def _replan(*_: object) -> str:
        raise RuntimeError("replan exploded")

    result = orchestrate_recovery(
        events,
        handlers={
            "retry_failed_actions": _retry,
            "replan_from_failed_stages": _replan,
        },
    )

    assert result.failed_stages == ["S2"]
    assert result.action_status_map == {
        "retry_failed_actions": "success",
        "replan_from_failed_stages": "failed",
        "escalate_to_human": "skipped",
    }
    assert result.should_escalate is True
    assert result.execution_report.failed_actions == ["replan_from_failed_stages"]


def test_orchestrate_recovery_no_failures_has_empty_summary() -> None:
    """No-failure inputs should produce a no-op orchestration summary."""
    events = [
        _evt("StageStateChanged", {"stage_id": "S1", "to_state": "active"}),
        _evt("ActionExecuted", {"stage_id": "S1", "success": True}),
        _evt("StageStateChanged", {"stage_id": "S1", "to_state": "completed"}),
    ]

    result = orchestrate_recovery(events, handlers={})

    assert result.failed_stages == []
    assert result.action_status_map == {}
    assert result.should_escalate is False
    assert result.execution_report.plan.actions == []


def test_orchestrate_recovery_satisfied_escalation_returns_false() -> None:
    """Successful escalation handler should mark escalation requirement as satisfied."""
    events = [_evt("StageStateChanged", {"stage_id": "S4", "to_state": "failed"})]

    def _escalate(*_: object) -> str:
        return "ticket-123"

    result = orchestrate_recovery(events, handlers={"escalate_to_human": _escalate})

    assert result.failed_stages == ["S4"]
    assert result.action_status_map == {"escalate_to_human": "success"}
    assert result.should_escalate is False
    assert result.execution_report.success is True
