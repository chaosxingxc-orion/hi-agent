"""Platform execution posture (dev / research / prod).

Controls which defaults are permissive (dev) vs fail-closed (research/prod).
Set via HI_AGENT_POSTURE environment variable; default is "dev".

Rule 11 — Posture-Aware Defaults: every config knob and persistence backend
declares its default behaviour under each posture. See docs/posture-reference.md.
"""

from __future__ import annotations

import os
from enum import StrEnum


class Posture(StrEnum):
    """Execution posture governing default safety behaviour.

    - DEV: permissive — missing scope emits warnings, in-memory backends allowed,
      schema validation warns and skips.
    - RESEARCH: fail-closed — project_id/profile_id required, durable backends
      default, schema validation raises on error, idempotency keyed on
      authenticated context.
    - PROD: strictest — same as RESEARCH plus additional security hardening.
    """

    DEV = "dev"
    RESEARCH = "research"
    PROD = "prod"

    @classmethod
    def from_env(cls) -> Posture:
        """Return posture from HI_AGENT_POSTURE; default DEV when unset."""
        raw = os.environ.get("HI_AGENT_POSTURE", "dev").strip().lower()
        try:
            return cls(raw)
        except ValueError:
            valid = ", ".join(p.value for p in cls)
            raise ValueError(
                f"HI_AGENT_POSTURE={raw!r} is not valid; expected one of: {valid}"
            ) from None

    @property
    def is_strict(self) -> bool:
        """True for research and prod (fail-closed). False for dev."""
        return self in (Posture.RESEARCH, Posture.PROD)

    @property
    def requires_project_id(self) -> bool:
        """project_id must be present on every run submission."""
        return self.is_strict

    @property
    def requires_profile_id(self) -> bool:
        """profile_id must be present on every run submission."""
        return self.is_strict

    @property
    def requires_durable_queue(self) -> bool:
        """RunQueue must be file-backed (SQLite), not in-memory."""
        return self.is_strict

    @property
    def requires_durable_ledger(self) -> bool:
        """ArtifactLedger must be file-backed, not in-memory."""
        return self.is_strict

    @property
    def requires_durable_registry(self) -> bool:
        """TeamRunRegistry must be file-backed, not in-memory dict."""
        return self.is_strict

    @property
    def requires_durable_backend(self) -> bool:
        """Alias: True when any durable backend is required (research/prod)."""
        return self.is_strict

    @property
    def requires_strict_profile_schema(self) -> bool:
        """Profile JSON parse errors raise ValueError instead of warn-and-skip."""
        return self.is_strict

    @property
    def requires_authenticated_idempotency_scope(self) -> bool:
        """IdempotencyStore must key on authenticated TenantContext, not request body."""
        return self.is_strict
