"""DEPRECATED — use ``hi_agent.runtime.harness.contracts`` instead.

Re-export shim retained until Wave 35 so callers using
``from hi_agent.harness.contracts import ...`` keep working.
"""

from hi_agent.runtime.harness.contracts import *  # noqa: F403  # expiry_wave: Wave 35
from hi_agent.runtime.harness.contracts import (  # noqa: F401  # expiry_wave: Wave 35
    ActionResult,
    ActionSpec,
    ActionState,
    EffectClass,
    EvidenceRecord,
    SideEffectClass,
)
