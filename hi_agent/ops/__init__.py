"""DEPRECATED — use ``hi_agent.operator_tools`` instead. Removed in W34.

This shim was added when ``hi_agent.ops`` was renamed to
``hi_agent.operator_tools`` to disambiguate it from
``hi_agent.operations`` (the long-running distributed coordinator/op-store/
poller substrate). ``operator_tools`` holds doctor/diagnostics/release-gate
helpers; ``operations`` holds the durable distributed-operation backbone.
"""

import warnings

warnings.warn(
    "hi_agent.ops is deprecated; use hi_agent.operator_tools",
    DeprecationWarning,
    stacklevel=2,
)
