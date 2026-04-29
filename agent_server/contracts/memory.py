"""Memory contract types."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryTierEnum(StrEnum):
    L0 = "L0"  # ephemeral, single run, in-process
    L1 = "L1"  # compressed, run-duration
    L2 = "L2"  # project-scoped index
    L3 = "L3"  # long-term knowledge graph


@dataclass(frozen=True)
class MemoryReadKey:
    """Key for reading from the memory tier."""

    tenant_id: str
    tier: MemoryTierEnum
    project_id: str = ""
    profile_id: str = ""
    run_id: str = ""
    key: str = ""


@dataclass(frozen=True)
class MemoryWriteRequest:
    """Request to write to the memory tier."""

    tenant_id: str
    tier: MemoryTierEnum
    key: str
    value: str  # serialized content
    project_id: str = ""
    profile_id: str = ""
    run_id: str = ""
    ttl_seconds: int = 0  # 0 = no expiry
