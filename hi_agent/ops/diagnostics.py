"""DEPRECATED — use ``hi_agent.operator_tools.diagnostics`` instead.

Re-export shim retained until Wave 36 so callers using
``from hi_agent.ops.diagnostics import ...`` keep working.
"""

from hi_agent.operator_tools.diagnostics import *  # noqa: F403  # expiry_wave: Wave 36
from hi_agent.operator_tools.diagnostics import (  # noqa: F401  # expiry_wave: Wave 36
    build_doctor_report,
)
