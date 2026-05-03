"""DEPRECATED — use ``hi_agent.operator_tools.release_gate`` instead.

Re-export shim retained until Wave 34 so callers using
``from hi_agent.ops.release_gate import ...`` keep working.
"""

from hi_agent.operator_tools.release_gate import *  # noqa: F403  # expiry_wave: Wave 34
from hi_agent.operator_tools.release_gate import (  # noqa: F401  # expiry_wave: Wave 34
    GateResult,
    ProdE2EResult,
    ReleaseGateReport,
    build_release_gate_report,
    check_prod_e2e_recent,
)
