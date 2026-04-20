"""Management subsystem exports."""

from hi_agent.management.alerts import evaluate_operational_alerts
from hi_agent.management.alerts_commands import cmd_alerts_ack, cmd_alerts_from_signals
from hi_agent.management.config_history import ConfigHistory, ConfigHistoryEntry
from hi_agent.management.gate_api import (
    GateAction,
    GateRecord,
    GateStatus,
    InMemoryGateAPI,
    resolve_gate_api,
)
from hi_agent.management.gate_commands import (
    cmd_gate_list,
    cmd_gate_list_pending,
    cmd_gate_operational_signal,
    cmd_gate_resolve,
    cmd_gate_status,
)
from hi_agent.management.gate_context import GateContext, build_gate_context
from hi_agent.management.gate_secure_commands import (
    MissingRoleClaimError,
    secure_cmd_gate_resolve,
)
from hi_agent.management.gate_timeout import (
    GateTimeoutPolicy,
    GateTimeoutResult,
    resolve_gate_timeout,
)
from hi_agent.management.health import (
    HealthReport,
    OperationalReadinessReport,
    ReadinessReport,
    SupervisorOperationalMetrics,
    basic_health_check,
    build_operational_readiness_from_signals,
    build_operational_readiness_report,
    operational_readiness_check,
    readiness_check,
)
from hi_agent.management.incident_commands import cmd_incident_close, cmd_incident_create
from hi_agent.management.incident_report import build_incident_report
from hi_agent.management.operational_dashboard import build_operational_dashboard_payload
from hi_agent.management.operational_signals import build_operational_signals
from hi_agent.management.ops_commands import cmd_ops_snapshot
from hi_agent.management.ops_report_commands import (
    cmd_ops_build_report,
    cmd_ops_build_runbook,
)
from hi_agent.management.ops_snapshot_commands import (
    cmd_ops_snapshot_latest,
    cmd_ops_snapshot_list,
    cmd_ops_snapshot_put,
)
from hi_agent.management.ops_snapshot_store import OpsSnapshotStore
from hi_agent.management.ops_timeline import build_ops_timeline
from hi_agent.management.ops_timeline_commands import (
    cmd_ops_timeline_build,
    cmd_ops_timeline_slice,
)
from hi_agent.management.reconcile_commands import (
    cmd_reconcile_manual,
    cmd_reconcile_readiness,
    cmd_reconcile_status,
)
from hi_agent.management.reconcile_daemon import ReconcileDaemon
from hi_agent.management.reconcile_metrics import (
    ReconcileMetricsSnapshot,
    build_reconcile_metrics_snapshot,
    build_reconcile_metrics_snapshot_from_controller,
)
from hi_agent.management.reconcile_runtime import (
    ReconcileRuntimeController,
    ReconcileRuntimeStatus,
)
from hi_agent.management.reconcile_supervisor import (
    ReconcileSupervisor,
    ReconcileSupervisorReport,
)
from hi_agent.management.runbook import build_incident_runbook
from hi_agent.management.runtime_config import (
    RuntimeConfigManager,
    RuntimeConfigSnapshot,
    RuntimeConfigStore,
    patch_runtime_config,
)
from hi_agent.management.runtime_config_commands import (
    cmd_runtime_config_get,
    cmd_runtime_config_history,
    cmd_runtime_config_patch,
)
from hi_agent.management.shutdown import (
    ShutdownHookError,
    ShutdownHookResult,
    ShutdownManager,
    ShutdownResult,
)
from hi_agent.management.slo import SLOSnapshot, build_slo_snapshot
from hi_agent.management.slo_commands import cmd_slo_burn_rate, cmd_slo_evaluate

__all__ = [
    "ConfigHistory",
    "ConfigHistoryEntry",
    "GateAction",
    "GateContext",
    "GateRecord",
    "GateStatus",
    "GateTimeoutPolicy",
    "GateTimeoutResult",
    "HealthReport",
    "InMemoryGateAPI",
    "MissingRoleClaimError",
    "OperationalReadinessReport",
    "OpsSnapshotStore",
    "ReadinessReport",
    "ReconcileDaemon",
    "ReconcileMetricsSnapshot",
    "ReconcileRuntimeController",
    "ReconcileRuntimeStatus",
    "ReconcileSupervisor",
    "ReconcileSupervisorReport",
    "RuntimeConfigManager",
    "RuntimeConfigSnapshot",
    "RuntimeConfigStore",
    "SLOSnapshot",
    "ShutdownHookError",
    "ShutdownHookResult",
    "ShutdownManager",
    "ShutdownResult",
    "SupervisorOperationalMetrics",
    "basic_health_check",
    "build_gate_context",
    "build_incident_report",
    "build_incident_runbook",
    "build_operational_dashboard_payload",
    "build_operational_readiness_from_signals",
    "build_operational_readiness_report",
    "build_operational_signals",
    "build_ops_timeline",
    "build_reconcile_metrics_snapshot",
    "build_reconcile_metrics_snapshot_from_controller",
    "build_slo_snapshot",
    "cmd_alerts_ack",
    "cmd_alerts_from_signals",
    "cmd_gate_list",
    "cmd_gate_list_pending",
    "cmd_gate_operational_signal",
    "cmd_gate_resolve",
    "cmd_gate_status",
    "cmd_incident_close",
    "cmd_incident_create",
    "cmd_ops_build_report",
    "cmd_ops_build_runbook",
    "cmd_ops_snapshot",
    "cmd_ops_snapshot_latest",
    "cmd_ops_snapshot_list",
    "cmd_ops_snapshot_put",
    "cmd_ops_timeline_build",
    "cmd_ops_timeline_slice",
    "cmd_reconcile_manual",
    "cmd_reconcile_readiness",
    "cmd_reconcile_status",
    "cmd_runtime_config_get",
    "cmd_runtime_config_history",
    "cmd_runtime_config_patch",
    "cmd_slo_burn_rate",
    "cmd_slo_evaluate",
    "evaluate_operational_alerts",
    "operational_readiness_check",
    "patch_runtime_config",
    "readiness_check",
    "resolve_gate_api",
    "resolve_gate_timeout",
    "secure_cmd_gate_resolve",
]
