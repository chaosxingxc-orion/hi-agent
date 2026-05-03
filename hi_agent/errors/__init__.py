"""DEPRECATED — use ``hi_agent.contracts.errors`` instead. Removed in W34.

This shim was added when ``hi_agent.errors.categories`` (the typed
hi-agent domain error hierarchy: ``TenantScopeError``, ``TransientError``,
``PermanentError``, ``IdempotencyConflictError``, …) was moved to
``hi_agent.contracts.errors`` so contract-boundary errors live alongside
the rest of the contracts vocabulary. The runtime trace failures continue
to live in ``hi_agent.failures``.
"""

import warnings

warnings.warn(
    "hi_agent.errors is deprecated; use hi_agent.contracts.errors",
    DeprecationWarning,
    stacklevel=2,
)

from hi_agent.contracts.errors import *  # noqa: F403  # expiry_wave: Wave 34
