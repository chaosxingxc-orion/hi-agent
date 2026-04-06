"""L1 compressed stage summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CompressedStageMemory:
    """Compressed stage representation for prompt context."""

    stage_id: str
    findings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    outcome: str = "active"
    contradiction_refs: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    source_evidence_count: int = 0
    compression_method: Literal["direct", "llm", "fallback"] = "direct"
