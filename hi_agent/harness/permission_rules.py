"""DEPRECATED — use ``hi_agent.runtime.harness.permission_rules`` instead.

Re-export shim retained until Wave 35 so callers using
``from hi_agent.harness.permission_rules import ...`` keep working.
"""

from hi_agent.runtime.harness.permission_rules import *  # noqa: F403  # expiry_wave: Wave 35
