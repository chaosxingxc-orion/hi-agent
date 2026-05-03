"""DEPRECATED — use ``hi_agent.operator_tools.doctor_report`` instead.

Re-export shim retained until Wave 34 so callers using
``from hi_agent.ops.doctor_report import ...`` keep working.
"""

from hi_agent.operator_tools.doctor_report import *  # noqa: F403  # expiry_wave: Wave 34
from hi_agent.operator_tools.doctor_report import (  # noqa: F401  # expiry_wave: Wave 34
    DoctorIssue,
    DoctorReport,
)
