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
# not directly from agent_kernel. Each name is annotated with one of:
#   scope: public-contract     — part of the documented agent_kernel ↔ hi_agent
#                                seam; downstream callers and hi_agent core
#                                code import these directly.
#   scope: process-internal    — implementation detail (event buffers,
#                                consistency journal, reconciler internals,
#                                summary command handlers). Re-exported here
#                                only because hi_agent runtime modules need
#                                a stable import path; not part of the
#                                documented contract surface.
# Annotation discipline added W32-D D.5 (annotation-only; no behavior change).
__all__ = [
    "FAILURE_GATE_MAP",                       # scope: public-contract
    "FAILURE_RECOVERY_MAP",                   # scope: public-contract
    "Action",                                 # scope: public-contract
    "AdapterHealthMonitor",                   # scope: public-contract
    "AsyncKernelFacadeAdapter",               # scope: public-contract
    "ConsistencyIssue",                       # scope: process-internal
    "ConsistencyIssueStatus",                 # scope: process-internal
    "ConsistencyReconcileReport",             # scope: process-internal
    "ConsistencyReconciler",                  # scope: process-internal
    "EventBuffer",                            # scope: process-internal
    "EventSummaryStore",                      # scope: process-internal
    "ExhaustedPolicy",                        # scope: public-contract
    "FileBackedConsistencyJournal",           # scope: process-internal
    "IllegalStateTransitionError",            # scope: public-contract
    "InMemoryConsistencyJournal",             # scope: process-internal
    "KernelFacadeAdapter",                    # scope: public-contract
    "KernelFacadeClient",                     # scope: public-contract
    "ReconcileLoop",                          # scope: process-internal
    "ReconcileLoopReport",                    # scope: process-internal
    "ResilientKernelAdapter",                 # scope: public-contract
    "RuntimeAdapter",                         # scope: public-contract
    "RuntimeAdapterBackendError",             # scope: public-contract
    "RuntimeAdapterError",                    # scope: public-contract
    "RuntimeEvent",                           # scope: public-contract
    "SideEffectClass",                        # scope: public-contract
    "SubstrateHealthChecker",                 # scope: public-contract
    "SubstrateHealthReport",                  # scope: public-contract
    "SubstrateNetworkState",                  # scope: public-contract
    "TaskAttempt",                            # scope: public-contract
    "TaskRestartPolicy",                      # scope: public-contract
    "TemporalConnectionHealthCheck",          # scope: public-contract
    "TemporalConnectionHealthReport",         # scope: public-contract
    "TemporalConnectionProbeResult",          # scope: public-contract
    "TemporalConnectionState",                # scope: public-contract
    "TraceFailureCode",                       # scope: public-contract
    "check_temporal_connection",              # scope: public-contract
    "cmd_event_summary_get",                  # scope: process-internal
    "cmd_event_summary_ingest",               # scope: process-internal
    "cmd_event_summary_list_runs",            # scope: process-internal
    "create_local_adapter",                   # scope: public-contract
    "summarize_runtime_events",               # scope: process-internal
]
