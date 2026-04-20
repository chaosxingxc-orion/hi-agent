"""Runtime adapter package."""

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

__all__ = [
    "AdapterHealthMonitor",
    "AsyncKernelFacadeAdapter",
    "ConsistencyIssue",
    "ConsistencyIssueStatus",
    "ConsistencyReconcileReport",
    "ConsistencyReconciler",
    "EventBuffer",
    "EventSummaryStore",
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
    "SubstrateHealthChecker",
    "SubstrateHealthReport",
    "SubstrateNetworkState",
    "TemporalConnectionHealthCheck",
    "TemporalConnectionHealthReport",
    "TemporalConnectionProbeResult",
    "TemporalConnectionState",
    "check_temporal_connection",
    "cmd_event_summary_get",
    "cmd_event_summary_ingest",
    "cmd_event_summary_list_runs",
    "create_local_adapter",
    "summarize_runtime_events",
]
