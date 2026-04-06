"""Tests for recovery compensation plan generator."""

from hi_agent.events import EventEnvelope
from hi_agent.recovery import (
    CompensationExecutionReport,
    CompensationPlan,
    build_compensation_plan,
    execute_compensation,
)


def _evt(event_type: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        run_id="run-1",
        payload=payload,
        timestamp="2026-04-05T00:00:00+00:00",
    )


def test_build_plan_no_failures() -> None:
    """Plan should stay empty when no failure event exists."""
    events = [
        _evt("StageStateChanged", {"stage_id": "S1", "to_state": "active"}),
        _evt("ActionExecuted", {"stage_id": "S1", "success": True}),
        _evt("StageStateChanged", {"stage_id": "S1", "to_state": "completed"}),
    ]

    plan = build_compensation_plan(events)

    assert isinstance(plan, CompensationPlan)
    assert plan.actions == []
    assert plan.reason == "no_failures_detected"
    assert plan.failed_stages == []


def test_build_plan_single_action_failure() -> None:
    """ActionExecutionFailed should suggest retry and replan."""
    events = [
        _evt(
            "ActionExecutionFailed",
            {
                "stage_id": "S2",
                "action_kind": "fetch_docs",
                "attempt": 1,
                "error": "timeout",
            },
        )
    ]

    plan = build_compensation_plan(events)

    assert plan.actions == ["retry_failed_actions", "replan_from_failed_stages"]
    assert plan.reason == "action_execution_failed"
    assert plan.failed_stages == ["S2"]


def test_build_plan_multi_failures_with_stage_failure() -> None:
    """Mixed failures should include retry/replan and escalate advice."""
    events = [
        _evt("ActionExecutionFailed", {"stage_id": "S2", "action_kind": "fetch_docs"}),
        _evt("ActionExecutionFailed", {"stage_id": "S3", "action_kind": "build_artifact"}),
        _evt("StageStateChanged", {"stage_id": "S3", "to_state": "failed"}),
    ]

    plan = build_compensation_plan(events)

    assert plan.actions == [
        "retry_failed_actions",
        "replan_from_failed_stages",
        "escalate_to_human",
    ]
    assert plan.reason == "mixed_failures_detected"
    assert plan.failed_stages == ["S2", "S3"]


def test_build_plan_dead_end_stage_failure() -> None:
    """Stage failed without action failure should be treated as dead-end."""
    events = [
        _evt("StageStateChanged", {"stage_id": "S4", "to_state": "active"}),
        _evt("StageStateChanged", {"stage_id": "S4", "to_state": "failed"}),
    ]

    plan = build_compensation_plan(events)

    assert plan.actions == ["escalate_to_human"]
    assert plan.reason == "dead_end_detected"
    assert plan.failed_stages == ["S4"]


def test_execute_compensation_successful_handlers() -> None:
    """Executor should run all planned handlers and mark them successful."""
    events = [
        _evt("ActionExecutionFailed", {"stage_id": "S2", "action_kind": "fetch_docs"}),
        _evt("StageStateChanged", {"stage_id": "S2", "to_state": "failed"}),
    ]
    call_order: list[str] = []

    def _retry(plan: CompensationPlan, consumed_events: tuple[EventEnvelope, ...]) -> str:
        call_order.append("retry")
        assert plan.reason == "mixed_failures_detected"
        assert consumed_events[0].event_type == "ActionExecutionFailed"
        return "retried"

    def _replan(plan: CompensationPlan, consumed_events: tuple[EventEnvelope, ...]) -> str:
        call_order.append("replan")
        assert plan.failed_stages == ["S2"]
        assert len(consumed_events) == 2
        return "replanned"

    def _escalate(plan: CompensationPlan, consumed_events: tuple[EventEnvelope, ...]) -> str:
        call_order.append("escalate")
        assert plan.actions[-1] == "escalate_to_human"
        assert consumed_events[-1].event_type == "StageStateChanged"
        return "ticket-1"

    report = execute_compensation(
        events,
        handlers={
            "retry_failed_actions": _retry,
            "replan_from_failed_stages": _replan,
            "escalate_to_human": _escalate,
        },
    )

    assert isinstance(report, CompensationExecutionReport)
    assert report.success is True
    assert report.succeeded_actions == [
        "retry_failed_actions",
        "replan_from_failed_stages",
        "escalate_to_human",
    ]
    assert report.failed_actions == []
    assert report.skipped_actions == []
    assert call_order == ["retry", "replan", "escalate"]


def test_execute_compensation_missing_handlers_are_skipped_safely() -> None:
    """Executor should skip actions with no handler instead of raising."""
    events = [_evt("ActionExecutionFailed", {"stage_id": "S2", "action_kind": "fetch_docs"})]

    report = execute_compensation(events, handlers={})

    assert report.success is True
    assert report.succeeded_actions == []
    assert report.failed_actions == []
    assert report.skipped_actions == [
        "retry_failed_actions",
        "replan_from_failed_stages",
    ]
    assert [result.status for result in report.results] == ["skipped", "skipped"]
    assert all(result.error is None for result in report.results)


def test_execute_compensation_handler_failure_is_recorded_and_continues() -> None:
    """Executor should continue running remaining actions after one handler fails."""
    events = [
        _evt("ActionExecutionFailed", {"stage_id": "S2", "action_kind": "fetch_docs"}),
        _evt("StageStateChanged", {"stage_id": "S2", "to_state": "failed"}),
    ]
    executed: list[str] = []

    def _retry(plan: CompensationPlan, consumed_events: tuple[EventEnvelope, ...]) -> None:
        _ = plan
        _ = consumed_events
        executed.append("retry")
        raise RuntimeError("retry exploded")

    def _replan(plan: CompensationPlan, consumed_events: tuple[EventEnvelope, ...]) -> str:
        _ = plan
        _ = consumed_events
        executed.append("replan")
        return "ok"

    report = execute_compensation(
        events,
        handlers={
            "retry_failed_actions": _retry,
            "replan_from_failed_stages": _replan,
        },
    )

    assert report.success is False
    assert report.succeeded_actions == ["replan_from_failed_stages"]
    assert report.failed_actions == ["retry_failed_actions"]
    assert report.skipped_actions == ["escalate_to_human"]
    assert executed == ["retry", "replan"]
    failure_result = report.results[0]
    assert failure_result.action == "retry_failed_actions"
    assert failure_result.status == "failed"
    assert failure_result.error == "retry exploded"
