"""Tenancy contract types."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """Identity and scope for a single tenant request."""

    tenant_id: str
    project_id: str = ""
    profile_id: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class TenantQuota:
    """Per-tenant resource quota configuration."""

    tenant_id: str
    max_concurrent_runs: int = 10
    max_runs_per_minute: int = 60
    max_llm_cost_per_day_usd: float = 100.0


@dataclass(frozen=True)
class CostEnvelope:
    """Tracked cost for a tenant over a billing window."""

    tenant_id: str
    window_start_iso: str
    window_end_iso: str
    llm_cost_usd: float = 0.0
    total_runs: int = 0
