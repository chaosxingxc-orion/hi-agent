"""Tenancy contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.tenancy")


@dataclass(frozen=True)
class TenantContext:
    """Identity and scope for a single tenant request."""

    tenant_id: str
    project_id: str = ""
    profile_id: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"TenantContext constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "tenant_context_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class TenantQuota:
    """Per-tenant resource quota configuration."""

    tenant_id: str
    max_concurrent_runs: int = 10
    max_runs_per_minute: int = 60
    max_llm_cost_per_day_usd: float = 100.0

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"TenantQuota constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "tenant_quota_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class CostEnvelope:
    """Tracked cost for a tenant over a billing window."""

    tenant_id: str
    window_start_iso: str
    window_end_iso: str
    llm_cost_usd: float = 0.0
    total_runs: int = 0

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.window_start_iso:
            missing.append("window_start_iso")
        if not self.window_end_iso:
            missing.append("window_end_iso")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"CostEnvelope constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "cost_envelope_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
