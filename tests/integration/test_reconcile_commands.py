"""Unit tests for management command-like reconcile helper API."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from hi_agent.management.health import OperationalReadinessReport
from hi_agent.management.reconcile_commands import (
    cmd_reconcile_manual,
    cmd_reconcile_readiness,
    cmd_reconcile_status,
)
from hi_agent.management.reconcile_runtime import ReconcileRuntimeStatus
from hi_agent.management.reconcile_supervisor import ReconcileSupervisorReport
from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoopReport


@dataclass
class _FakeController:
    manual_report: ReconcileSupervisorReport
    status_report: ReconcileRuntimeStatus
    readiness_report: OperationalReadinessReport

    def __post_init__(self) -> None:
        self.manual_calls: list[int] = []
        self.readiness_calls: list[int] = []

    def run_manual(self, max_rounds: int) -> ReconcileSupervisorReport:
        self.manual_calls.append(max_rounds)
        return self.manual_report

    def status(self) -> ReconcileRuntimeStatus:
        return self.status_report

    def readiness(self, *, recent_error_count: int = 0) -> OperationalReadinessReport:
        self.readiness_calls.append(recent_error_count)
        return self.readiness_report


def _build_controller() -> _FakeController:
    return _FakeController(
        manual_report=ReconcileSupervisorReport(
            trigger="manual",
            executed=True,
            timestamp_seconds=123.5,
            backlog_size=0,
            max_rounds=3,
            recent_reconcile_failures=0,
            reconcile_report=ReconcileLoopReport(
                rounds=1,
                applied=1,
                failed=0,
                skipped=0,
                dead_letter_count=0,
            ),
        ),
        status_report=ReconcileRuntimeStatus(
            backlog_size=2,
            recent_reconcile_failures=1,
            dead_letter_count=1,
            last_trigger="manual",
            last_executed=True,
        ),
        readiness_report=OperationalReadinessReport(
            ready=False,
            dependencies={"runtime": True, "kernel": False},
            recent_error_count=2,
            reconcile_backlog=2,
            recent_reconcile_failures=1,
            reconcile_backlog_threshold=2,
        ),
    )


def test_cmd_reconcile_manual_returns_stable_primitive_payload() -> None:
    """Manual command payload should be stable and primitive-only."""
    controller = _build_controller()

    payload = cmd_reconcile_manual(controller, max_rounds=3)

    assert controller.manual_calls == [3]
    assert payload == {
        "command": "reconcile_manual",
        "trigger": "manual",
        "executed": True,
        "timestamp_seconds": 123.5,
        "backlog_size": 0,
        "max_rounds": 3,
        "recent_reconcile_failures": 0,
        "reconcile_rounds": 1,
        "reconcile_applied": 1,
        "reconcile_failed": 0,
        "reconcile_skipped": 0,
        "reconcile_dead_letter_count": 0,
    }


def test_cmd_reconcile_status_returns_stable_primitive_payload() -> None:
    """Status command payload should be stable and primitive-only."""
    controller = _build_controller()

    payload = cmd_reconcile_status(controller)

    assert payload == {
        "command": "reconcile_status",
        "backlog_size": 2,
        "recent_reconcile_failures": 1,
        "dead_letter_count": 1,
        "last_trigger": "manual",
        "last_executed": True,
    }


def test_cmd_reconcile_readiness_returns_stable_primitive_payload() -> None:
    """Readiness command payload should be stable and primitive-only."""
    controller = _build_controller()

    payload = cmd_reconcile_readiness(controller, recent_error_count=2)

    assert controller.readiness_calls == [2]
    assert payload == {
        "command": "reconcile_readiness",
        "ready": False,
        "dependencies": {"runtime": True, "kernel": False},
        "recent_error_count": 2,
        "reconcile_backlog": 2,
        "recent_reconcile_failures": 1,
        "reconcile_backlog_threshold": 2,
    }


@pytest.mark.parametrize("value", [0, -1])
def test_cmd_reconcile_manual_rejects_non_positive_max_rounds(value: int) -> None:
    """Manual command should reject max_rounds values below one."""
    controller = _build_controller()

    with pytest.raises(ValueError, match="max_rounds must be >= 1"):
        cmd_reconcile_manual(controller, max_rounds=value)


@pytest.mark.parametrize("value", [True, False, 1.5, "1", None])
def test_cmd_reconcile_manual_rejects_invalid_max_rounds_types(value: object) -> None:
    """Manual command should reject non-int max_rounds values."""
    controller = _build_controller()

    with pytest.raises(TypeError, match="max_rounds must be an int"):
        cmd_reconcile_manual(controller, max_rounds=value)


def test_cmd_reconcile_readiness_rejects_negative_recent_error_count() -> None:
    """Readiness command should reject negative recent_error_count values."""
    controller = _build_controller()

    with pytest.raises(ValueError, match="recent_error_count must be >= 0"):
        cmd_reconcile_readiness(controller, recent_error_count=-1)


@pytest.mark.parametrize("value", [True, False, 1.5, "1", None])
def test_cmd_reconcile_readiness_rejects_invalid_recent_error_count_types(
    value: object,
) -> None:
    """Readiness command should reject non-int recent_error_count values."""
    controller = _build_controller()

    with pytest.raises(TypeError, match="recent_error_count must be an int"):
        cmd_reconcile_readiness(controller, recent_error_count=value)
