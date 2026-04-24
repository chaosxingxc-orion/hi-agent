"""agent_kernel.kernel — kernel contracts and execution primitives. Public surface."""

from agent_kernel.kernel.contracts import (
    Action,
    CancelRunRequest,
    OpenBranchRequest,
    QueryRunRequest,
    ResumeRunRequest,
    RuntimeEvent,
    SideEffectClass,
    SignalRunRequest,
    SpawnChildRunRequest,
    StartRunRequest,
    TaskViewRecord,
    TraceFailureCode,
)
from agent_kernel.kernel.failure_mappings import (
    FAILURE_GATE_MAP,
    FAILURE_RECOVERY_MAP,
)
from agent_kernel.kernel.task_manager.contracts import (
    ExhaustedPolicy,
    TaskAttempt,
    TaskRestartPolicy,
)

__all__ = [
    "FAILURE_GATE_MAP",
    "FAILURE_RECOVERY_MAP",
    "Action",
    "CancelRunRequest",
    "ExhaustedPolicy",
    "OpenBranchRequest",
    "QueryRunRequest",
    "ResumeRunRequest",
    "RuntimeEvent",
    "SideEffectClass",
    "SignalRunRequest",
    "SpawnChildRunRequest",
    "StartRunRequest",
    "TaskAttempt",
    "TaskRestartPolicy",
    "TaskViewRecord",
    "TraceFailureCode",
]
