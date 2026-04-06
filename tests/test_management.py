"""Tests for management subsystem."""

from hi_agent.management import (
    OperationalReadinessReport,
    ReconcileDaemon,
    ReconcileMetricsSnapshot,
    ReconcileRuntimeController,
    ReconcileRuntimeStatus,
    ReconcileSupervisor,
    ReconcileSupervisorReport,
    ShutdownManager,
    basic_health_check,
    build_operational_readiness_report,
    build_reconcile_metrics_snapshot,
    build_reconcile_metrics_snapshot_from_controller,
    cmd_reconcile_manual,
    cmd_reconcile_readiness,
    cmd_reconcile_status,
    operational_readiness_check,
)


def test_basic_health_check() -> None:
    """Health report should mark unhealthy components."""
    report = basic_health_check({"runtime": True, "db": False})
    assert report.healthy is False
    assert "db" in report.details["unhealthy"]


def test_shutdown_manager_runs_hooks_in_reverse_order() -> None:
    """Shutdown hooks should run in LIFO order."""
    order: list[str] = []
    manager = ShutdownManager()
    manager.register_hook(lambda: order.append("first"))
    manager.register_hook(lambda: order.append("second"))

    manager.run()

    assert order == ["second", "first"]


def test_management_exports_operational_readiness_symbols() -> None:
    """Management package should export operational readiness helpers."""
    assert OperationalReadinessReport.__name__ == "OperationalReadinessReport"
    assert ReconcileDaemon.__name__ == "ReconcileDaemon"
    assert ReconcileMetricsSnapshot.__name__ == "ReconcileMetricsSnapshot"
    assert ReconcileRuntimeController.__name__ == "ReconcileRuntimeController"
    assert ReconcileRuntimeStatus.__name__ == "ReconcileRuntimeStatus"
    assert ReconcileSupervisor.__name__ == "ReconcileSupervisor"
    assert ReconcileSupervisorReport.__name__ == "ReconcileSupervisorReport"
    assert callable(cmd_reconcile_manual)
    assert callable(cmd_reconcile_readiness)
    assert callable(cmd_reconcile_status)
    assert callable(build_reconcile_metrics_snapshot)
    assert callable(build_reconcile_metrics_snapshot_from_controller)
    assert callable(operational_readiness_check)
    assert callable(build_operational_readiness_report)
