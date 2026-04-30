"""Trajectory node contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NodeType(StrEnum):
    """Node semantic types used by trajectory DAG."""

    DECISION = "decision"
    ACTION = "action"
    EVIDENCE = "evidence"
    SYNTHESIS = "synthesis"
    CHECKPOINT = "checkpoint"


class NodeState(StrEnum):
    """Execution states for trajectory nodes."""

    OPEN = "open"
    EXPANDED = "expanded"
    PRUNED = "pruned"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# scope: process-internal — pure value object (CLAUDE.md Rule 12 carve-out)
@dataclass
class TrajectoryNode:
    """A node in trajectory DAG."""

    node_id: str
    node_type: NodeType
    stage_id: str
    branch_id: str
    parent_ids: list[str] = field(default_factory=list)
    children_ids: list[str] = field(default_factory=list)
    description: str = ""
    action_ref: str | None = None
    evidence_ref: str | None = None
    local_score: float = 0.0
    propagated_score: float = 0.0
    visit_count: int = 0
    state: NodeState = NodeState.OPEN
