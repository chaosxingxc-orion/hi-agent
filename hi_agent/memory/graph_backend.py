"""Abstract protocol for knowledge graph backends.

Platform provides JsonGraphBackend (LongTermMemoryGraph).
Downstream can implement Neo4jGraphBackend or other backends by satisfying this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class Edge:
    """A directed edge in the knowledge graph."""

    src: str
    dst: str
    relation: str
    payload: dict[str, Any]


@dataclass
class Path:
    """A path through the knowledge graph."""

    nodes: list[str]
    edges: list[Edge]


@dataclass
class ConflictReport:
    """Report of a detected conflict between two claims."""

    claim_a: str
    claim_b: str
    conflict_type: str
    description: str


@runtime_checkable
class KnowledgeGraphBackend(Protocol):
    """Protocol that any KG backend implementation must satisfy.

    Platform provides :class:`JsonGraphBackend` (alias for
    :class:`~hi_agent.memory.long_term.LongTermMemoryGraph`) as the default
    implementation.  Downstream teams can substitute a different backend —
    such as Neo4j — by implementing this protocol.
    """

    def upsert_node(self, node_id: str, payload: dict[str, Any]) -> None:
        """Insert or update a node by ID."""
        ...

    def upsert_edge(
        self, src: str, dst: str, relation: str, payload: dict[str, Any]
    ) -> None:
        """Insert or update a directed edge."""
        ...

    def query_relation(
        self, node_id: str, relation: str, direction: str
    ) -> list[Edge]:
        """Return edges matching the given relation from/to node_id.

        Args:
            node_id: Source or target node ID.
            relation: Edge relation type filter.
            direction: ``"out"`` for outgoing, ``"in"`` for incoming,
                ``"both"`` for either direction.
        """
        ...

    def transitive_query(
        self, start: str, relation: str, max_depth: int
    ) -> list[Path]:
        """Return all paths reachable from *start* via *relation* up to *max_depth* hops."""
        ...

    def detect_conflict(
        self, claim_a: str, claim_b: str
    ) -> ConflictReport | None:
        """Check whether claim_a and claim_b conflict.

        Returns a :class:`ConflictReport` if a conflict is detected, else ``None``.
        """
        ...

    def export_visualization(
        self, format: str  # noqa: A002 — shadowing built-in intentional in protocol
    ) -> str:
        """Export the graph for visualization.

        Args:
            format: ``"graphml"`` or ``"cytoscape"``.

        Returns:
            The serialized graph as a string in the requested format.
        """
        ...
