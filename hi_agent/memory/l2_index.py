"""L2 run-level memory index."""

from __future__ import annotations

from dataclasses import dataclass, field


# Pointer in RunMemoryIndex.stages.
# scope: process-internal — the parent RunMemoryIndex carries the spine.
@dataclass
class StagePointer:
    """Pointer metadata for one stage snapshot."""

    stage_id: str
    outcome: str


@dataclass
class RunMemoryIndex:
    """Compact index for navigating compressed memory.

    Wave 24 H1: tenant_id is part of the spine so the L2 index can be
    partitioned per-tenant when persisted.
    """

    run_id: str
    stages: list[StagePointer] = field(default_factory=list)
    tenant_id: str = ""  # scope: spine-required — enforced under strict posture

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict and not self.tenant_id:
            raise ValueError(
                "RunMemoryIndex.tenant_id required under research/prod posture"
            )

    def add_stage(self, stage_id: str, outcome: str) -> None:
        """Append stage pointer."""
        self.stages.append(StagePointer(stage_id=stage_id, outcome=outcome))
