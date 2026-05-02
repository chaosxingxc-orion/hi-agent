"""DEPRECATED — use ``hi_agent.contracts.errors`` instead.

Re-export shim retained until Wave 34 so callers using
``from hi_agent.errors.categories import ...`` keep working.
"""

from hi_agent.contracts.errors import *  # noqa: F401, F403  # expiry_wave: Wave 34
from hi_agent.contracts.errors import (  # noqa: F401  # expiry_wave: Wave 34
    EventBufferOverflowError,
    HiAgentError,
    IdempotencyConflictError,
    LLMRateLimitError,
    LLMTimeoutError,
    LeaseLostError,
    PermanentError,
    ProfileScopeError,
    RunQueueFullError,
    TenantScopeError,
    TransientError,
)
