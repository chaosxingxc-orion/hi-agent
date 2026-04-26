"""Artifact-subsystem metrics counters (Rule 7 compliance).

Provides thread-safe counters for legacy tenantless artifact events so
every silent-degradation path is countable and attributable.

Counter names follow the hi_agent_ prefix convention used across the
observability module.
"""
from __future__ import annotations

import threading


class _SimpleCounter:
    """Thread-safe monotonic counter with posture label support."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._lock = threading.Lock()
        self._values: dict[str, int] = {}

    def inc(self, posture: str = "unknown") -> None:
        """Increment the counter for the given posture label."""
        with self._lock:
            self._values[posture] = self._values.get(posture, 0) + 1

    def get(self, posture: str = "unknown") -> int:
        """Return current counter value for the given posture label."""
        with self._lock:
            return self._values.get(posture, 0)

    def total(self) -> int:
        """Return total across all posture labels."""
        with self._lock:
            return sum(self._values.values())

    def reset(self) -> None:
        """Reset all counters (for testing only)."""
        with self._lock:
            self._values.clear()


# hi_agent_legacy_tenantless_artifact_denied_total
# Incremented when a legacy (tenant_id="") artifact is denied under strict posture.
legacy_tenantless_denied_total = _SimpleCounter(
    "hi_agent_legacy_tenantless_artifact_denied_total",
    "Total legacy tenantless artifacts denied due to strict posture.",
)

# hi_agent_legacy_tenantless_artifact_visible_total
# Incremented when a legacy (tenant_id="") artifact is allowed under dev posture.
legacy_tenantless_visible_total = _SimpleCounter(
    "hi_agent_legacy_tenantless_artifact_visible_total",
    "Total legacy tenantless artifacts allowed in dev posture.",
)
