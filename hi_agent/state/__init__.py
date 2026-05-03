"""DEPRECATED — use ``hi_agent.run_state_store`` instead. Removed in W34.

This shim was added when ``hi_agent.state`` (one file: RunStateSnapshot,
RunStateStore) was renamed to ``hi_agent.run_state_store`` to disambiguate
from ``hi_agent.state_machine`` (formal FSM definitions).
"""

import warnings

warnings.warn(
    "hi_agent.state is deprecated; use hi_agent.run_state_store",
    DeprecationWarning,
    stacklevel=2,
)

from hi_agent.run_state_store import *  # noqa: F403  # expiry_wave: Wave 34
