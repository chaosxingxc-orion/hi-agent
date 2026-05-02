"""Run state persistence primitives.

This package was renamed from ``hi_agent.state`` to disambiguate it from
``hi_agent.state_machine`` (which holds the formal FSM definitions). The
legacy ``hi_agent.state`` import path still works via a deprecation shim
and will be removed in Wave 34.
"""

from hi_agent.run_state_store.run_state import RunStateSnapshot, RunStateStore

__all__ = ["RunStateSnapshot", "RunStateStore"]
