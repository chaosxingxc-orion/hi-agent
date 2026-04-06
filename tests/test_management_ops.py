"""Operational tests for management readiness and shutdown."""

from __future__ import annotations

import time

from hi_agent.management import (
    ShutdownManager,
    build_operational_readiness_report,
    readiness_check,
)
from hi_agent.management.health import operational_readiness_check


def test_readiness_check_reports_dependencies_and_recent_error_count() -> None:
    """Readiness should expose dependency map and recent error count."""
    report = readiness_check({"runtime": True, "db": False}, recent_error_count=2)

    assert report.ready is False
    assert report.dependencies == {"runtime": True, "db": False}
    assert report.recent_error_count == 2


def test_operational_readiness_check_requires_clean_recent_signals() -> None:
    """Operational readiness needs healthy deps, no recent failures, and low backlog."""
    report = operational_readiness_check(
        {"runtime": True, "db": True},
        recent_error_count=0,
        reconcile_backlog=2,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=5,
    )

    assert report.ready is True
    assert report.dependencies == {"runtime": True, "db": True}
    assert report.recent_error_count == 0
    assert report.reconcile_backlog == 2
    assert report.recent_reconcile_failures == 0
    assert report.reconcile_backlog_threshold == 5


def test_operational_readiness_check_flags_backlog_and_reconcile_failures() -> None:
    """Backlog at/over threshold or reconcile failures should make report not ready."""
    backlog_blocked = operational_readiness_check(
        {"runtime": True},
        recent_error_count=0,
        reconcile_backlog=10,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=10,
    )
    failure_blocked = operational_readiness_check(
        {"runtime": True},
        recent_error_count=0,
        reconcile_backlog=0,
        recent_reconcile_failures=1,
        reconcile_backlog_threshold=10,
    )

    assert backlog_blocked.ready is False
    assert failure_blocked.ready is False


def test_operational_readiness_check_validates_non_negative_inputs() -> None:
    """Operational readiness should reject negative counters and backlog."""
    try:
        operational_readiness_check(
            {"runtime": True},
            recent_error_count=-1,
            reconcile_backlog=0,
            recent_reconcile_failures=0,
            reconcile_backlog_threshold=10,
        )
    except ValueError as exc:
        assert "recent_error_count must be >= 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for recent_error_count")

    try:
        operational_readiness_check(
            {"runtime": True},
            recent_error_count=0,
            reconcile_backlog=-1,
            recent_reconcile_failures=0,
            reconcile_backlog_threshold=10,
        )
    except ValueError as exc:
        assert "reconcile_backlog must be >= 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for reconcile_backlog")

    try:
        operational_readiness_check(
            {"runtime": True},
            recent_error_count=0,
            reconcile_backlog=0,
            recent_reconcile_failures=-1,
            reconcile_backlog_threshold=10,
        )
    except ValueError as exc:
        assert "recent_reconcile_failures must be >= 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for recent_reconcile_failures")

    try:
        operational_readiness_check(
            {"runtime": True},
            recent_error_count=0,
            reconcile_backlog=0,
            recent_reconcile_failures=0,
            reconcile_backlog_threshold=-1,
        )
    except ValueError as exc:
        assert "reconcile_backlog_threshold must be >= 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for reconcile_backlog_threshold")


def test_build_operational_readiness_report_from_supervisor_like_metrics() -> None:
    """Helper should accept a metrics object with supervisor-like attributes."""

    class _Metrics:
        def __init__(self) -> None:
            self.dependencies = {"runtime": True, "db": True}
            self.recent_error_count = 0
            self.reconcile_backlog = 3
            self.recent_reconcile_failures = 0
            self.reconcile_backlog_threshold = 10

    report = build_operational_readiness_report(metrics=_Metrics())

    assert report.ready is True
    assert report.dependencies == {"runtime": True, "db": True}
    assert report.recent_error_count == 0
    assert report.reconcile_backlog == 3
    assert report.recent_reconcile_failures == 0
    assert report.reconcile_backlog_threshold == 10


def test_build_operational_readiness_report_with_explicit_args() -> None:
    """Helper should support explicit values when metrics object is not passed."""
    report = build_operational_readiness_report(
        dependencies={"runtime": True},
        recent_error_count=0,
        reconcile_backlog=2,
        recent_reconcile_failures=0,
        reconcile_backlog_threshold=5,
    )

    assert report.ready is True
    assert report.dependencies == {"runtime": True}
    assert report.recent_error_count == 0
    assert report.reconcile_backlog == 2
    assert report.recent_reconcile_failures == 0
    assert report.reconcile_backlog_threshold == 5


def test_shutdown_manager_continues_after_timeout() -> None:
    """One slow hook timing out should not block remaining hooks."""
    observed: list[str] = []

    def fast_hook() -> None:
        observed.append("fast")

    def slow_hook() -> None:
        time.sleep(0.25)

    manager = ShutdownManager()
    manager.register_hook(fast_hook)
    manager.register_hook(slow_hook)

    start = time.perf_counter()
    result = manager.run(hook_timeout_seconds=0.05)
    elapsed = time.perf_counter() - start

    assert observed == ["fast"]
    assert elapsed < 0.20
    assert result.ok is False
    assert result.total_hooks == 2
    assert result.timed_out_hooks == 1
    assert result.failed_hooks == 0


def test_shutdown_manager_aggregates_exceptions_without_interrupting() -> None:
    """All hooks should run and exceptions should be captured in result."""
    observed: list[str] = []

    def final_hook() -> None:
        observed.append("final")

    def value_error_hook() -> None:
        raise ValueError("bad input")

    def runtime_error_hook() -> None:
        raise RuntimeError("boom")

    manager = ShutdownManager()
    manager.register_hook(final_hook)
    manager.register_hook(value_error_hook)
    manager.register_hook(runtime_error_hook)

    result = manager.run()

    assert observed == ["final"]
    assert result.ok is False
    assert result.total_hooks == 3
    assert result.failed_hooks == 2
    assert result.timed_out_hooks == 0
    assert {item.hook_name for item in result.errors} == {
        "runtime_error_hook",
        "value_error_hook",
    }
    assert {item.error_message for item in result.errors} == {"boom", "bad input"}
