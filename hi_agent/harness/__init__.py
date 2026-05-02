"""DEPRECATED — use ``hi_agent.runtime.harness`` instead. Removed in W34.

This shim was added when the harness subsystem was moved from
``hi_agent.harness`` into ``hi_agent.runtime.harness`` so the runtime helper
namespace is unified (sync_bridge, profile_runtime, cancellation, harness).
"""

import warnings

warnings.warn(
    "hi_agent.harness is deprecated; use hi_agent.runtime.harness",
    DeprecationWarning,
    stacklevel=2,
)

from hi_agent.runtime.harness import *  # noqa: F401, F403, E402  # expiry_wave: Wave 34
