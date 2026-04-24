"""Tests for the recovery/compensation subsystem."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from hi_agent.events import EventEnvelope, make_envelope
from hi_agent.recovery import (
    CompensationExecutionReport,
    CompensationPlan,
    build_compensation_plan,
    execute_compensation,
    orchestrate_recovery,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action_failed_event(stage_id: str = "s1") -> EventEnvelope:
    return make_envelope("ActionExecutionFailed", "run-1", {"stage_id": stage_id})


def _stage_failed_event(stage_id: str = "s1") -> EventEnvelope:
    return make_envelope("StageStateChanged", "run-1", {"stage_id": stage_id, "to_state": "failed"})


def _benign_event() -> EventEnvelope:
    return make_envelope("SomethingElse", "run-1", {})


# ---------------------------------------------------------------------------
# 1. Register and invoke compensation handler
# ---------------------------------------------------------------------------


class TestRegisterAndInvokeHandler:
    def test_handler_is_called_with_plan_and_events(self):
        events = [_action_failed_event("s1")]
        handler = MagicMock(return_value="handled")

        report = execute_compensation(events, handlers={"retry_failed_actions": handler})

        handler.assert_called_once()
        plan_arg, events_arg = handler.call_args[0]
        assert isinstance(plan_arg, CompensationPlan)
        assert isinstance(events_arg, tuple)
        assert report.succeeded_actions == ["retry_failed_actions"]
        assert report.success is True

    def test_handler_return_value_captured_in_result(self):
        events = [_action_failed_event()]
        handler = MagicMock(return_value={"retried": True})

        report = execute_compensation(events, handlers={"retry_failed_actions": handler})

        assert report.results[0].output == {"retried": True}
        assert report.results[0].status == "success"


# ---------------------------------------------------------------------------
# 2. Compensation succeeds
# ---------------------------------------------------------------------------


class TestCompensationSucceeds:
    def test_all_handlers_succeed(self):
        events = [_action_failed_event(), _stage_failed_event()]
        handlers = {
            "retry_failed_actions": lambda p, e: "ok",
            "replan_from_failed_stages": lambda p, e: "ok",
            "escalate_to_human": lambda p, e: "escalated",
        }

        report = execute_compensation(events, handlers=handlers)

        assert report.success is True
        assert len(report.succeeded_actions) == 3
        assert report.failed_actions == []
        assert report.skipped_actions == []


# ---------------------------------------------------------------------------
# 3. Compensation fails gracefully
# ---------------------------------------------------------------------------


class TestCompensationFailsGracefully:
    def test_handler_exception_captured_without_propagating(self):
        events = [_action_failed_event()]

        def boom(plan, evts):
            raise RuntimeError("disk full")

        report = execute_compensation(events, handlers={"retry_failed_actions": boom})

        assert report.success is False
        assert "retry_failed_actions" in report.failed_actions
        assert report.results[0].status == "failed"
        assert "disk full" in report.results[0].error


# ---------------------------------------------------------------------------
# 4. Orchestrator sequences compensations in reverse-plan order
# ---------------------------------------------------------------------------


class TestOrchestratorSequencing:
    def test_actions_execute_in_plan_order(self):
        """Verify actions are invoked in the order they appear in the plan."""
        call_order: list[str] = []
        events = [_action_failed_event(), _stage_failed_event()]

        def make_handler(name: str):
            def handler(p, e):
                call_order.append(name)

            return handler

        handlers = {
            "retry_failed_actions": make_handler("retry_failed_actions"),
            "replan_from_failed_stages": make_handler("replan_from_failed_stages"),
            "escalate_to_human": make_handler("escalate_to_human"),
        }

        result = orchestrate_recovery(events, handlers=handlers)

        # mixed_failures_detected plan: retry, replan, escalate
        assert call_order == [
            "retry_failed_actions",
            "replan_from_failed_stages",
            "escalate_to_human",
        ]
        assert result.should_escalate is False
        assert result.failed_stages == ["s1"]

    def test_orchestrator_escalation_signal_when_escalate_handler_missing(self):
        events = [_action_failed_event(), _stage_failed_event()]
        # Provide handlers for everything except escalate_to_human
        handlers = {
            "retry_failed_actions": lambda p, e: None,
            "replan_from_failed_stages": lambda p, e: None,
        }

        result = orchestrate_recovery(events, handlers=handlers)

        assert result.should_escalate is True
        assert result.action_status_map["escalate_to_human"] == "skipped"


# ---------------------------------------------------------------------------
# 5. Partial compensation (some succeed, some fail)
# ---------------------------------------------------------------------------


class TestPartialCompensation:
    def test_mixed_success_and_failure(self):
        events = [_action_failed_event(), _stage_failed_event()]
        handlers = {
            "retry_failed_actions": lambda p, e: "ok",
            "replan_from_failed_stages": lambda p, e: (_ for _ in ()).throw(
                ValueError("bad stage")
            ),
            "escalate_to_human": lambda p, e: "escalated",
        }

        report = execute_compensation(events, handlers=handlers)

        assert report.success is False
        assert "retry_failed_actions" in report.succeeded_actions
        assert "replan_from_failed_stages" in report.failed_actions
        assert "escalate_to_human" in report.succeeded_actions

    def test_orchestrator_should_escalate_on_partial_failure(self):
        events = [_action_failed_event()]
        handlers = {
            "retry_failed_actions": lambda p, e: (_ for _ in ()).throw(RuntimeError("fail")),
            "replan_from_failed_stages": lambda p, e: "ok",
        }

        result = orchestrate_recovery(events, handlers=handlers)

        assert result.should_escalate is True


# ---------------------------------------------------------------------------
# 6. No compensation registered -> skip gracefully
# ---------------------------------------------------------------------------


class TestNoCompensationRegistered:
    def test_no_handlers_all_skipped(self):
        events = [_action_failed_event()]

        report = execute_compensation(events, handlers=None)

        assert report.success is True
        assert len(report.skipped_actions) == len(report.plan.actions)
        assert report.failed_actions == []

    def test_no_failures_in_events_yields_empty_plan(self):
        events = [_benign_event()]

        report = execute_compensation(events)

        assert report.plan.actions == []
        assert report.plan.reason == "no_failures_detected"
        assert report.results == []
        assert report.success is True


# ---------------------------------------------------------------------------
# 7. Concurrent compensation safety
# ---------------------------------------------------------------------------


class TestConcurrentCompensationSafety:
    def test_concurrent_execute_compensation_calls(self):
        """Multiple threads can run execute_compensation without interference."""
        events_a = [_action_failed_event("sa")]
        events_b = [_stage_failed_event("sb")]

        results: dict[str, CompensationExecutionReport] = {}
        errors: list[Exception] = []

        def run(key, events, handlers):
            try:
                results[key] = execute_compensation(events, handlers=handlers)
            except Exception as exc:
                errors.append(exc)

        handler_a = MagicMock(return_value="a")
        handler_b = MagicMock(return_value="b")

        t1 = threading.Thread(
            target=run,
            args=("a", events_a, {"retry_failed_actions": handler_a}),
        )
        t2 = threading.Thread(
            target=run,
            args=("b", events_b, {"escalate_to_human": handler_b}),
        )

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Unexpected errors: {errors}"
        assert results["a"].succeeded_actions == ["retry_failed_actions"]
        assert results["b"].succeeded_actions == ["escalate_to_human"]


# ---------------------------------------------------------------------------
# 8. build_compensation_plan edge cases
# ---------------------------------------------------------------------------


class TestBuildCompensationPlan:
    def test_action_failure_only(self):
        plan = build_compensation_plan([_action_failed_event("s1")])
        assert plan.reason == "action_execution_failed"
        assert "retry_failed_actions" in plan.actions
        assert plan.failed_stages == ["s1"]

    def test_stage_failure_only(self):
        plan = build_compensation_plan([_stage_failed_event("s2")])
        assert plan.reason == "dead_end_detected"
        assert plan.actions == ["escalate_to_human"]
        assert plan.failed_stages == ["s2"]

    def test_deduplicates_failed_stages(self):
        plan = build_compensation_plan(
            [
                _action_failed_event("s1"),
                _action_failed_event("s1"),
                _stage_failed_event("s1"),
            ]
        )
        assert plan.failed_stages == ["s1"]
