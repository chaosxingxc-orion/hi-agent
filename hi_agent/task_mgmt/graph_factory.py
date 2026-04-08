"""Complexity-driven graph template factory.

Given a TaskContract and a ComplexityScore from RouteEngine,
builds the initial TrajectoryGraph for AsyncTaskScheduler.
Nodes are added dynamically during execution via add_node().
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hi_agent.trajectory.graph import TrajectoryGraph, TrajNode


@dataclass
class ComplexityScore:
    score: float                        # 0.0 (trivial) → 1.0 (very complex)
    needs_parallel_gather: bool = False
    needs_speculative: bool = False
    metadata: dict = field(default_factory=dict)


def _make_node(node_id: str, description: str) -> TrajNode:
    return TrajNode(
        node_id=node_id,
        node_type="task",
        payload={"description": description},
    )


class GraphFactory:
    """Builds initial TrajectoryGraph based on task complexity."""

    def build(self, contract, complexity: ComplexityScore) -> TrajectoryGraph:
        if complexity.score < 0.3:
            return self._build_simple()
        elif complexity.needs_parallel_gather:
            return self._build_parallel_gather()
        elif complexity.needs_speculative:
            return self._build_speculative()
        else:
            return self._build_standard()

    def _build_simple(self) -> TrajectoryGraph:
        """S1 → S3 → S5, light models throughout."""
        g = TrajectoryGraph()
        nodes = [
            _make_node("S1", "Understand task"),
            _make_node("S3", "Build / analyze"),
            _make_node("S5", "Review output"),
        ]
        for n in nodes:
            g.add_node(n)
        g.add_sequence("S1", "S3")
        g.add_sequence("S3", "S5")
        return g

    def _build_standard(self) -> TrajectoryGraph:
        """S1 → S2 → S3 → S4 → S5, tier routing per stage."""
        g = TrajectoryGraph()
        stage_ids = ["S1", "S2", "S3", "S4", "S5"]
        descriptions = [
            "Understand task", "Gather information",
            "Build / analyze", "Synthesize", "Review output",
        ]
        nodes = [_make_node(sid, desc) for sid, desc in zip(stage_ids, descriptions)]
        for n in nodes:
            g.add_node(n)
        for i in range(len(nodes) - 1):
            g.add_sequence(nodes[i].node_id, nodes[i + 1].node_id)
        return g

    def _build_parallel_gather(self) -> TrajectoryGraph:
        """S1 → [S2-a, S2-b, S2-c] → S3 → S4 → S5."""
        g = TrajectoryGraph()
        gather_nodes = ["S2-a", "S2-b", "S2-c"]
        all_nodes = (
            [_make_node("S1", "Understand task")]
            + [_make_node(nid, f"Gather ({nid})") for nid in gather_nodes]
            + [
                _make_node("S3", "Build / analyze"),
                _make_node("S4", "Synthesize"),
                _make_node("S5", "Review output"),
            ]
        )
        for n in all_nodes:
            g.add_node(n)
        for gn in gather_nodes:
            g.add_sequence("S1", gn)
            g.add_sequence(gn, "S3")
        g.add_sequence("S3", "S4")
        g.add_sequence("S4", "S5")
        return g

    def _build_speculative(self) -> TrajectoryGraph:
        """S1 → S2 → [S3-v1, S3-v2] (speculative) → S4 → S5."""
        g = TrajectoryGraph()
        candidates = ["S3-v1", "S3-v2"]
        nodes = (
            [_make_node("S1", "Understand task"), _make_node("S2", "Gather information")]
            + [_make_node(c, f"Build candidate {c}") for c in candidates]
            + [_make_node("S4", "Synthesize"), _make_node("S5", "Review output")]
        )
        for n in nodes:
            g.add_node(n)
        g.add_sequence("S1", "S2")
        for c in candidates:
            g.add_sequence("S2", c)
            g.add_sequence(c, "S4")
        g.add_sequence("S4", "S5")
        return g
