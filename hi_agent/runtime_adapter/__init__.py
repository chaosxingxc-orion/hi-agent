"""Runtime adapter package — kernel facade adapter spine.

This is the seam between hi_agent and agent_kernel. It re-exports the
production kernel contract surface (FAILURE_GATE_MAP, Action, RuntimeEvent,
TaskAttempt, …) and the adapter implementations. Test fixtures
(``InMemoryDedupeStore``, ``InMemoryKernelRuntimeEventLog``,
``StaticRecoveryGateService``) live in :mod:`hi_agent.testing` instead of
here so production callers do not pull in test-only primitives.
"""

from agent_kernel.kernel import (
    FAILURE_GATE_MAP,
    FAILURE_RECOVERY_MAP,
    Action,
    ExhaustedPolicy,
    RuntimeEvent,
    SideEffectClass,
    TaskAttempt,
    TaskRestartPolicy,
    TraceFailureCode,
)
from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
    AsyncKernelFacadeAdapter,
)
from hi_agent.runtime_adapter.consistency import (
    ConsistencyIssue,
    FileBackedConsistencyJournal,
    InMemoryConsistencyJournal,
)
from hi_agent.runtime_adapter.errors import (
    IllegalStateTransitionError,
    RuntimeAdapterBackendError,
    RuntimeAdapterError,
)
from hi_agent.runtime_adapter.event_buffer import EventBuffer
from hi_agent.runtime_adapter.event_stream_summary import summarize_runtime_events
from hi_agent.runtime_adapter.event_summary_commands import (
    cmd_event_summary_get,
    cmd_event_summary_ingest,
    cmd_event_summary_list_runs,
)
from hi_agent.runtime_adapter.event_summary_store import EventSummaryStore
from hi_agent.runtime_adapter.health import AdapterHealthMonitor
from hi_agent.runtime_adapter.kernel_facade_adapter import (
    KernelFacadeAdapter,
    create_local_adapter,
)
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoop, ReconcileLoopReport
from hi_agent.runtime_adapter.reconciler import (
    ConsistencyIssueStatus,
    ConsistencyReconciler,
    ConsistencyReconcileReport,
)
from hi_agent.runtime_adapter.resilient_kernel_adapter import ResilientKernelAdapter
from hi_agent.runtime_adapter.temporal_health import (
    SubstrateHealthChecker,
    SubstrateHealthReport,
    SubstrateNetworkState,
    TemporalConnectionHealthCheck,
    TemporalConnectionHealthReport,
    TemporalConnectionProbeResult,
    TemporalConnectionState,
    check_temporal_connection,
)

# Kernel contract re-exports — hi_agent modules import these from here,
# not directly from agent_kernel.
__all__ = [
    "FAILURE_GATE_MAP",
    "FAILURE_RECOVERY_MAP",
    "Action",
    "AdapterHealthMonitor",
    "AsyncKernelFacadeAdapter",
    "ConsistencyIssue",
    "ConsistencyIssueStatus",
    "ConsistencyReconcileReport",
    "ConsistencyReconciler",
    "EventBuffer",
    "EventSummaryStore",
    "ExhaustedPolicy",
    "FileBackedConsistencyJournal",
    "IllegalStateTransitionError",
    "InMemoryConsistencyJournal",
    "KernelFacadeAdapter",
    "KernelFacadeClient",
    "ReconcileLoop",
    "ReconcileLoopReport",
    "ResilientKernelAdapter",
    "RuntimeAdapter",
    "RuntimeAdapterBackendError",
    "RuntimeAdapterError",
    "RuntimeEvent",
    "SideEffectClass",
    "SubstrateHealthChecker",
    "SubstrateHealthReport",
    "SubstrateNetworkState",
    "TaskAttempt",
    "TaskRestartPolicy",
    "TemporalConnectionHealthCheck",
    "TemporalConnectionHealthReport",
    "TemporalConnectionProbeResult",
    "TemporalConnectionState",
    "TraceFailureCode",
    "check_temporal_connection",
    "cmd_event_summary_get",
    "cmd_event_summary_ingest",
    "cmd_event_summary_list_runs",
    "create_local_adapter",
    "summarize_runtime_events",
]
