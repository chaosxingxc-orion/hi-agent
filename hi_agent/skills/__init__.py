"""DEPRECATED — use ``hi_agent.skill_runtime`` instead. Removed in W34.

This shim was added in Wave 31 (W31-H.1) when ``hi_agent.skills`` was renamed
to ``hi_agent.skill_runtime`` to distinguish lifecycle (``hi_agent.skill``)
from runtime strategy (``hi_agent.skill_runtime``).
"""

import warnings

warnings.warn(
    "hi_agent.skills is deprecated; use hi_agent.skill_runtime",
    DeprecationWarning,
    stacklevel=2,
)

from hi_agent.skill_runtime import *  # noqa: F401, F403, E402  # expiry_wave: Wave 34
