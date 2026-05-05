"""DEPRECATED — use ``hi_agent.contracts.errors`` instead.

Re-export shim retained until Wave 35 so callers using
``from hi_agent.errors.categories import ...`` keep working.
"""

from hi_agent.contracts.errors import *  # noqa: F403  # expiry_wave: Wave 35
from hi_agent.contracts.errors import (  # noqa: F401  # expiry_wave: Wave 35
    EventBufferOverflowError,
    HiAgentError,
    IdempotencyConflictError,
    LeaseLostError,
    LLMRateLimitError,
    LLMTimeoutError,
    PermanentError,
    ProfileScopeError,
    RunQueueFullError,
    TenantScopeError,
    TransientError,
)
