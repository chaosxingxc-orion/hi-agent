"""Deployment posture enum for hi-agent.

Posture controls enforcement strictness for project_id, profile_id,
durable backends, and schema validation.

Resolution order:
1. Explicit argument to ``Posture.from_env()``
2. ``HI_AGENT_POSTURE`` environment variable
3. Falls back to ``Posture.DEV``
"""

from __future__ import annotations

import os
from enum import StrEnum


class Posture(StrEnum):
    """Deployment posture: dev < research < prod (strictness order)."""

    DEV = "dev"
    RESEARCH = "research"
    PROD = "prod"

    @classmethod
    def from_env(cls) -> Posture:
        """Read posture from HI_AGENT_POSTURE env var, default to DEV."""
        raw = os.environ.get("HI_AGENT_POSTURE", "").strip().lower()
        if not raw:
            return cls.DEV
        try:
            return cls(raw)
        except ValueError:
            valid = [p.value for p in cls]
            raise ValueError(
                f"HI_AGENT_POSTURE={raw!r} is not valid. "
                f"Valid values: {valid}"
            ) from None

    @property
    def requires_project_id(self) -> bool:
        """Whether this posture enforces project_id on POST /runs."""
        return self in (Posture.RESEARCH, Posture.PROD)

    @property
    def requires_profile_id(self) -> bool:
        """Whether this posture enforces profile_id on POST /runs."""
        return self in (Posture.RESEARCH, Posture.PROD)

    @property
    def requires_durable_backend(self) -> bool:
        """Whether this posture requires durable queue/ledger backends."""
        return self in (Posture.RESEARCH, Posture.PROD)


def get_posture() -> Posture:
    """Return the current deployment posture from the environment."""
    return Posture.from_env()
