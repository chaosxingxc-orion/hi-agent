"""hi-agent package.

Module split rule (errors / failures):

- ``hi_agent.contracts.errors`` — contract-boundary typed errors
  (``TransientError``, ``PermanentError``, ``TenantScopeError``,
  ``IdempotencyConflictError``, ``LLMTimeoutError``, …). Raised at
  contract boundaries; consumed by callers that need to switch on
  error category.
- ``hi_agent.failures`` — runtime trace failures (collector, watchdog,
  taxonomy). The runtime emits these into the trace stream; they are
  observability artifacts, not raised exceptions.

The legacy ``hi_agent.errors`` import path still works via a
deprecation shim (re-exporting from ``hi_agent.contracts.errors``) and
will be removed in Wave 34.
"""

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
    "check_readiness",
]
