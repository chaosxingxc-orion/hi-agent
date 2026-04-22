"""hi-agent package."""

__version__ = "0.1.0"

from hi_agent.executor_facade import (
    ReadinessReport,
    RunExecutorFacade,
    RunFacadeResult,
    check_readiness,
)
from hi_agent.gate_protocol import GateEvent, GatePendingError
from hi_agent.runner import SubRunHandle, SubRunResult

__all__ = [
    "GateEvent",
    "GatePendingError",
    "ReadinessReport",
    "RunExecutorFacade",
    "RunFacadeResult",
    "SubRunHandle",
    "SubRunResult",
    "__version__",
    "check_readiness",
]
