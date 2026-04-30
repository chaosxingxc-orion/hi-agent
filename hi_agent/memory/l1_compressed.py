"""L1 compressed stage summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CompressedStageMemory:
    """Compressed stage representation for prompt context.

    Wave 24 H1: tenant_id is part of the spine so L1 compressed stage memory
    can be partitioned per-tenant when persisted to JSONL.
    """

    stage_id: str
    findings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    outcome: str = "active"
    contradiction_refs: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    source_evidence_count: int = 0
    compression_method: Literal["direct", "llm", "fallback"] = "direct"
    tenant_id: str = ""  # scope: spine-required — enforced under strict posture

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict and not self.tenant_id:
            raise ValueError(
                "CompressedStageMemory.tenant_id required under research/prod posture"
            )
