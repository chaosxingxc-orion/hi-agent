"""DEPRECATED — use ``hi_agent.runtime.harness.executor`` instead.

Re-export shim retained until Wave 35 so callers using
``from hi_agent.harness.executor import ...`` keep working.
"""

from hi_agent.runtime.harness.executor import *  # noqa: F403  # expiry_wave: Wave 35
from hi_agent.runtime.harness.executor import (  # noqa: F401  # expiry_wave: Wave 35
    HarnessExecutor,
)
