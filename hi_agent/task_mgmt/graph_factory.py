"""Complexity-driven graph template factory.

Given a TaskContract and a ComplexityScore from RouteEngine,
builds the initial TrajectoryGraph for AsyncTaskScheduler.
Nodes are added dynamically during execution via add_node().
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from hi_agent.trajectory.graph import TrajectoryGraph, TrajNode

# Keywords that signal parallel/gather intent
_PARALLEL_KEYWORDS = re.compile(
    r"\b(compare|multiple|parallel|gather|versus|vs\.?|side.by.side)\b",
    re.IGNORECASE,
)
_PARALLEL_AND_PATTERN = re.compile(
    r"\b(analyze|evaluate|review|assess|examine|check)\b.+\band\b",
    re.IGNORECASE,
)

# Keywords that signal speculative/exploratory intent
_SPECULATIVE_KEYWORDS = re.compile(
    r"\b(explore|alternative|speculative|try.different|brainstorm|what.if|experiment)\b",
    re.IGNORECASE,
)

# Task families considered simple
_SIMPLE_FAMILIES = frozenset({"quick_task", "simple", ""})


@dataclass
class ComplexityScore:
    """ComplexityScore class."""
    score: float                        # 0.0 (trivial) → 1.0 (very complex)
    needs_parallel_gather: bool = False
    needs_speculative: bool = False
    metadata: dict = field(default_factory=dict)


def _make_node(node_id: str, description: str) -> TrajNode:
    """Run _make_node."""
    return TrajNode(
        node_id=node_id,
        node_type="task",
        payload={"description": description},
    )


class GraphFactory:
    """Builds initial TrajectoryGraph based on task complexity."""

    # Ordered template names for external reference
    TEMPLATES = ("simple", "standard", "parallel_gather", "speculative")

    def build(self, contract, complexity: ComplexityScore) -> TrajectoryGraph:
        """Build a graph from an explicit ComplexityScore (original API)."""
        if complexity.score < 0.3:
            return self._build_simple()
        elif complexity.needs_parallel_gather:
            return self._build_parallel_gather()
        elif complexity.needs_speculative:
            return self._build_speculative()
        else:
            return self._build_standard()

    # ------------------------------------------------------------------
    # Auto-select: analyse goal text to pick the right template
    # ------------------------------------------------------------------

    def auto_select(
        self,
        goal: str,
        task_family: str = "",
        hints: dict | None = None,
    ) -> tuple[str, TrajectoryGraph]:
        """Choose a template by analysing *goal* text and optional *hints*.

        Returns ``(template_name, graph)`` so callers know which template
        was selected.
        """
        template = self._estimate_complexity(goal, task_family, hints)
        graph = self._build_by_name(template)
        return template, graph

    def _estimate_complexity(
        self,
        goal: str,
        task_family: str,
        hints: dict | None,
    ) -> str:
        """Return the template name best matching the inputs."""
        hints = hints or {}

        # Explicit hint overrides take priority
        if hints.get("speculative"):
            return "speculative"
        if hints.get("parallel"):
            return "parallel_gather"

        # Keyword matching on goal text
        if _SPECULATIVE_KEYWORDS.search(goal):
            return "speculative"
        if _PARALLEL_KEYWORDS.search(goal) or _PARALLEL_AND_PATTERN.search(goal):
            return "parallel_gather"

        # Short, simple goals
        if len(goal) < 50 and task_family in _SIMPLE_FAMILIES:
            return "simple"

        # Default
        return "standard"

    def _build_by_name(self, name: str) -> TrajectoryGraph:
        """Dispatch to the named builder."""
        builders = {
            "simple": self._build_simple,
            "standard": self._build_standard,
            "parallel_gather": self._build_parallel_gather,
            "speculative": self._build_speculative,
        }
        builder = builders.get(name)
        if builder is None:
            raise ValueError(f"Unknown template: {name!r}")
        return builder()

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
        nodes = [_make_node(sid, desc) for sid, desc in zip(stage_ids, descriptions, strict=False)]
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
