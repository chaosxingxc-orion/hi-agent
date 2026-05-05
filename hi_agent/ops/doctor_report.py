"""DEPRECATED — use ``hi_agent.operator_tools.doctor_report`` instead.

Re-export shim retained until Wave 35 so callers using
``from hi_agent.ops.doctor_report import ...`` keep working.
"""

from hi_agent.operator_tools.doctor_report import *  # noqa: F403  # expiry_wave: Wave 35
from hi_agent.operator_tools.doctor_report import (  # noqa: F401  # expiry_wave: Wave 35
    DoctorIssue,
    DoctorReport,
)
