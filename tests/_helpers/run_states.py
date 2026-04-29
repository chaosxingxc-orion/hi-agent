"""Run state partitions for honest test assertions (AX-B B2).

Use SUCCESS_STATES for happy-path assertions.
Use FAILURE_STATES only in chaos/error scenario tests.
Use TERMINAL_STATES when you genuinely need all terminal states.
"""
from __future__ import annotations

# States that represent successful completion
SUCCESS_STATES: frozenset[str] = frozenset({"done", "completed"})

# States that represent failures (should NOT appear in happy-path assertions)
FAILURE_STATES: frozenset[str] = frozenset({"failed", "error", "timed_out", "aborted", "cancelled"})

# All terminal states (use only in chaos tests that validate fail-fast)
TERMINAL_STATES: frozenset[str] = SUCCESS_STATES | FAILURE_STATES
