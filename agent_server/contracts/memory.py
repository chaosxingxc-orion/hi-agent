"""Memory contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.memory")


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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness.

        ``tier`` is structurally required by the constructor signature
        (no default), so the only field that can sneak through empty is
        ``tenant_id``.
        """
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"MemoryReadKey constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "memory_read_key_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.key:
            missing.append("key")
        if not self.value:
            missing.append("value")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"MemoryWriteRequest constructed without required spine fields "
                f"under posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "memory_write_request_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
