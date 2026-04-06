"""L2 run-level memory index."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StagePointer:
    """Pointer metadata for one stage snapshot."""

    stage_id: str
    outcome: str


@dataclass
class RunMemoryIndex:
    """Compact index for navigating compressed memory."""

    run_id: str
    stages: list[StagePointer] = field(default_factory=list)

    def add_stage(self, stage_id: str, outcome: str) -> None:
        """Append stage pointer."""
        self.stages.append(StagePointer(stage_id=stage_id, outcome=outcome))
