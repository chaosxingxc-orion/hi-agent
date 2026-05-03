"""SQLite-backed KnowledgeGraphBackend.

Implements the KnowledgeGraphBackend Protocol defined in
``hi_agent.memory.graph_backend`` using a local SQLite file.

All queries filter by tenant_id to prevent cross-tenant leaks (Rule 12).
The backend satisfies the Protocol contract exactly — same method signatures
as LongTermMemoryGraph (JsonGraphBackend).

Schema
------
kg_nodes(id, tenant_id, project_id, payload, created_at)
kg_edges(src, dst, relation, tenant_id, project_id, payload, created_at)

# scope: process-internal
# Reason: SqliteKnowledgeGraphBackend is not yet wired into server/app.py.
# make_knowledge_graph_backend() will be called inside the builder and injected
# via DI.  Until then, the factory is ready but server wiring is intentionally
# deferred.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


class SqliteKnowledgeGraphBackend:
    """SQLite implementation of the KnowledgeGraphBackend Protocol.

    Args:
        db_path: Path to the SQLite file.  Pass ``:memory:`` for tests.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS kg_nodes (
        id         TEXT NOT NULL,
        tenant_id  TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        payload    TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        PRIMARY KEY (id, tenant_id)
    );
    CREATE TABLE IF NOT EXISTS kg_edges (
        src        TEXT NOT NULL,
        dst        TEXT NOT NULL,
        relation   TEXT NOT NULL,
        tenant_id  TEXT NOT NULL,
        project_id TEXT NOT NULL DEFAULT '',
        payload    TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        PRIMARY KEY (src, dst, relation, tenant_id)
    );
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # Track D C-1: WAL + busy_timeout via shared helper.
        from hi_agent._sqlite_init import configure_sqlite_connection
        configure_sqlite_connection(self._conn)
        self._conn.executescript(self._DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # KnowledgeGraphBackend Protocol methods
    # ------------------------------------------------------------------

    def upsert_node(self, node_id: str, payload: dict[str, Any]) -> None:
        """Insert or update a node by ID.

        The payload dict may carry ``tenant_id`` and ``project_id`` fields;
        those are extracted and stored in their own columns so that all
        queries can filter by tenant.
        """
        tenant_id = str(payload.get("tenant_id", ""))
        project_id = str(payload.get("project_id", ""))
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO kg_nodes (id, tenant_id, project_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (node_id, tenant_id, project_id, json.dumps(payload), now),
        )
        self._conn.commit()

    def upsert_edge(
        self, src: str, dst: str, relation: str, payload: dict[str, Any]
    ) -> None:
        """Insert or update a directed edge.

        The payload dict may carry ``tenant_id`` and ``project_id`` fields.
        """
        tenant_id = str(payload.get("tenant_id", ""))
        project_id = str(payload.get("project_id", ""))
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO kg_edges
                (src, dst, relation, tenant_id, project_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (src, dst, relation, tenant_id, project_id, json.dumps(payload), now),
        )
        self._conn.commit()

    def query_relation(
        self, node_id: str, relation: str, direction: str
    ) -> list[Any]:
        """Return Edge objects matching the given relation.

        Args:
            node_id: Source or target node ID.
            relation: Edge relation type filter.
            direction: ``"out"`` for outgoing, ``"in"`` for incoming,
                ``"both"`` for either direction.

        Returns edges filtered by the tenant_id stored in the node's payload.
        When the node has no tenant_id, edges with empty tenant_id are returned.
        """
        from hi_agent.memory.graph_backend import Edge as _GEdge

        # Resolve the tenant_id from the node row so the edge query stays scoped.
        node_row = self._conn.execute(
            "SELECT tenant_id FROM kg_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        tenant_id = node_row[0] if node_row else ""

        rows: list[Any] = []
        if direction in ("out", "both"):
            cur = self._conn.execute(
                """
                SELECT src, dst, relation, payload
                FROM kg_edges
                WHERE src = ? AND relation = ? AND tenant_id = ?
                """,
                (node_id, relation, tenant_id),
            )
            for src, dst, rel, payload_str in cur:
                rows.append(
                    _GEdge(
                        src=src,
                        dst=dst,
                        relation=rel,
                        payload=json.loads(payload_str),
                    )
                )
        if direction in ("in", "both"):
            cur = self._conn.execute(
                """
                SELECT src, dst, relation, payload
                FROM kg_edges
                WHERE dst = ? AND relation = ? AND tenant_id = ?
                """,
                (node_id, relation, tenant_id),
            )
            for src, dst, rel, payload_str in cur:
                rows.append(
                    _GEdge(
                        src=src,
                        dst=dst,
                        relation=rel,
                        payload=json.loads(payload_str),
                    )
                )
        return rows

    def transitive_query(self, start: str, relation: str, max_depth: int) -> list[Any]:
        """Return all paths reachable from *start* via *relation* up to *max_depth* hops.

        Uses iterative BFS rather than a recursive CTE so the depth limit
        is enforced in application code (SQLite does not guarantee CTE
        recursion depth limits are honoured on all builds).
        """
        from hi_agent.memory.graph_backend import Edge as _GEdge
        from hi_agent.memory.graph_backend import Path as _GPath

        # Resolve tenant_id from start node.
        node_row = self._conn.execute(
            "SELECT tenant_id FROM kg_nodes WHERE id = ?",
            (start,),
        ).fetchone()
        tenant_id = node_row[0] if node_row else ""

        visited: set[str] = {start}
        frontier: list[str] = [start]
        # path_to[node] = (parent_path_nodes, parent_path_edges)
        path_to: dict[str, tuple[list[str], list[Any]]] = {
            start: ([start], [])
        }

        for _depth in range(max_depth):
            if not frontier:
                break
            next_frontier: list[str] = []
            for current in frontier:
                cur = self._conn.execute(
                    """
                    SELECT src, dst, relation, payload
                    FROM kg_edges
                    WHERE src = ? AND relation = ? AND tenant_id = ?
                    """,
                    (current, relation, tenant_id),
                )
                for src, dst, rel, payload_str in cur:
                    if dst not in visited:
                        visited.add(dst)
                        next_frontier.append(dst)
                        parent_nodes, parent_edges = path_to[current]
                        edge = _GEdge(
                            src=src,
                            dst=dst,
                            relation=rel,
                            payload=json.loads(payload_str),
                        )
                        path_to[dst] = (
                            [*parent_nodes, dst],
                            [*parent_edges, edge],
                        )
            frontier = next_frontier

        paths: list[_GPath] = []
        for node_id, (nodes, edges) in path_to.items():
            if node_id == start:
                continue
            paths.append(_GPath(nodes=nodes, edges=edges))
        return paths

    def detect_conflict(self, claim_a: str, claim_b: str) -> Any | None:
        """Check whether claim_a and claim_b conflict via a 'contradicts' edge.

        Returns a ConflictReport if an edge with relation='contradicts' exists
        between the two nodes, else None.
        """
        from hi_agent.memory.graph_backend import ConflictReport

        row = self._conn.execute(
            """
            SELECT src, dst FROM kg_edges
            WHERE relation = 'contradicts'
              AND ((src = ? AND dst = ?) OR (src = ? AND dst = ?))
            LIMIT 1
            """,
            (claim_a, claim_b, claim_b, claim_a),
        ).fetchone()
        if row is None:
            return None
        return ConflictReport(
            claim_a=claim_a,
            claim_b=claim_b,
            conflict_type="contradicts",
            description=(
                f"Edge with relation='contradicts' exists between {claim_a} and {claim_b}"
            ),
        )

    def export_visualization(self, format: str) -> str:
        """Export the graph for visualization.

        Args:
            format: ``"graphml"`` or ``"cytoscape"``.

        Returns:
            JSON string with ``format``, ``nodes``, and ``edges`` keys.
        """
        nodes_cur = self._conn.execute("SELECT id, payload FROM kg_nodes")
        nodes = [
            {"id": row[0], **json.loads(row[1])}
            for row in nodes_cur
        ]
        edges_cur = self._conn.execute("SELECT src, dst, relation, payload FROM kg_edges")
        edges = [
            {"src": row[0], "dst": row[1], "relation": row[2], **json.loads(row[3])}
            for row in edges_cur
        ]
        return json.dumps(
            {"format": format, "nodes": nodes, "edges": edges},
            ensure_ascii=False,
        )

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
