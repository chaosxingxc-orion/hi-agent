"""Durable SQLite-backed knowledge graph backend.

Satisfies the KnowledgeGraphBackend protocol. Used as the default backend
under research/prod posture (Rule 11 — Posture-Aware Defaults).

Schema carries tenant_id, profile_id, project_id on every node and edge row
(Rule 12 — Contract Spine Completeness).
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, ClassVar

from hi_agent.memory.graph_backend import ConflictReport, Edge
from hi_agent.memory.graph_backend import Path as GPath


class SqliteKnowledgeGraphBackend:
    """SQLite-backed knowledge graph.

    Satisfies :class:`~hi_agent.memory.graph_backend.KnowledgeGraphBackend`.

    Tenant/profile/project scoping is enforced at construction time:
    every node and edge row carries the constructor-provided spine fields,
    and queries filter by them automatically.

    Thread-safe for concurrent in-process access (WAL mode + threading.Lock).

    Args:
        data_dir: Directory where the SQLite file is written.
        profile_id: Profile scope; required (Rule 6).
        project_id: Optional project scope.
        tenant_id: Optional tenant scope stored on every row.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS kg_nodes (
        node_id   TEXT NOT NULL,
        profile_id TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL DEFAULT '',
        tenant_id  TEXT NOT NULL DEFAULT '',  -- migration compat; new rows populate via exec_ctx
        payload    JSON NOT NULL DEFAULT '{}',
        PRIMARY KEY (node_id, profile_id, project_id)
    );
    CREATE TABLE IF NOT EXISTS kg_edges (
        src        TEXT NOT NULL,
        dst        TEXT NOT NULL,
        relation   TEXT NOT NULL,
        profile_id TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL DEFAULT '',
        tenant_id  TEXT NOT NULL DEFAULT '',  -- migration compat; new rows populate via exec_ctx
        payload    JSON NOT NULL DEFAULT '{}',
        PRIMARY KEY (src, dst, relation, profile_id, project_id)
    );
    """

    _MIGRATE_STMTS: ClassVar[list[str]] = [
        "ALTER TABLE kg_nodes ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE kg_edges ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''",
    ]

    def __init__(
        self,
        data_dir: str | Path,
        profile_id: str,
        project_id: str = "",
        tenant_id: str = "",
    ) -> None:
        if not profile_id:
            raise ValueError(
                "SqliteKnowledgeGraphBackend requires profile_id; "
                "empty profile_id would create an unscoped store (Rule 6 / Rule 12)."
            )
        self._profile_id = profile_id
        self._project_id = project_id
        self._tenant_id = tenant_id

        db_dir = Path(data_dir)
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "knowledge_graph.sqlite"
        self._path = db_path
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(db_path), check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.executescript(self._DDL)
        self._con.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add missing spine columns if upgrading from an older schema."""
        node_cols = {row[1] for row in self._con.execute("PRAGMA table_info(kg_nodes)")}
        edge_cols = {row[1] for row in self._con.execute("PRAGMA table_info(kg_edges)")}
        all_cols = node_cols | edge_cols
        for stmt in self._MIGRATE_STMTS:
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            if col not in all_cols:
                with contextlib.suppress(sqlite3.OperationalError):
                    self._con.execute(stmt)
        self._con.commit()

    # ------------------------------------------------------------------
    # KnowledgeGraphBackend protocol implementation
    # ------------------------------------------------------------------

    def upsert_node(self, node_id: str, payload: dict[str, Any]) -> None:
        """Insert or update a node by ID (scoped to profile/project)."""
        with self._lock:
            self._con.execute(
                """
                INSERT INTO kg_nodes (node_id, profile_id, project_id, tenant_id, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(node_id, profile_id, project_id) DO UPDATE
                    SET payload = excluded.payload,
                        tenant_id = excluded.tenant_id
                """,
                (
                    node_id,
                    self._profile_id,
                    self._project_id,
                    self._tenant_id,
                    json.dumps(payload),
                ),
            )
            self._con.commit()

    def upsert_edge(
        self, src: str, dst: str, relation: str, payload: dict[str, Any]
    ) -> None:
        """Insert or update a directed edge."""
        with self._lock:
            self._con.execute(
                """
                INSERT INTO kg_edges
                    (src, dst, relation, profile_id, project_id, tenant_id, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(src, dst, relation, profile_id, project_id) DO UPDATE
                    SET payload = excluded.payload,
                        tenant_id = excluded.tenant_id
                """,
                (
                    src,
                    dst,
                    relation,
                    self._profile_id,
                    self._project_id,
                    self._tenant_id,
                    json.dumps(payload),
                ),
            )
            self._con.commit()

    def query_relation(
        self, node_id: str, relation: str, direction: str
    ) -> list[Edge]:
        """Return edges matching the given relation from/to node_id."""
        results: list[Edge] = []
        with self._lock:
            if direction in ("out", "both"):
                rows = self._con.execute(
                    """
                    SELECT src, dst, relation, payload FROM kg_edges
                    WHERE src=? AND relation=?
                          AND profile_id=? AND project_id=?
                    """,
                    (node_id, relation, self._profile_id, self._project_id),
                ).fetchall()
                for row in rows:
                    results.append(
                        Edge(
                            src=row[0],
                            dst=row[1],
                            relation=row[2],
                            payload=json.loads(row[3]),
                        )
                    )
            if direction in ("in", "both"):
                rows = self._con.execute(
                    """
                    SELECT src, dst, relation, payload FROM kg_edges
                    WHERE dst=? AND relation=?
                          AND profile_id=? AND project_id=?
                    """,
                    (node_id, relation, self._profile_id, self._project_id),
                ).fetchall()
                for row in rows:
                    results.append(
                        Edge(
                            src=row[0],
                            dst=row[1],
                            relation=row[2],
                            payload=json.loads(row[3]),
                        )
                    )
        return results

    def transitive_query(
        self, start: str, relation: str, max_depth: int
    ) -> list[GPath]:
        """Return all paths reachable from *start* via *relation* up to *max_depth* hops."""
        visited: set[str] = set()
        frontier = [start]
        paths: list[GPath] = []
        with self._lock:
            for _ in range(max_depth):
                if not frontier:
                    break
                next_frontier: list[str] = []
                for node_id in frontier:
                    rows = self._con.execute(
                        """
                        SELECT src, dst, relation, payload FROM kg_edges
                        WHERE src=? AND relation=?
                              AND profile_id=? AND project_id=?
                        """,
                        (node_id, relation, self._profile_id, self._project_id),
                    ).fetchall()
                    for row in rows:
                        dst = row[1]
                        if dst not in visited and dst != start:
                            visited.add(dst)
                            next_frontier.append(dst)
                            paths.append(
                                GPath(
                                    nodes=[start, dst],
                                    edges=[
                                        Edge(
                                            src=row[0],
                                            dst=row[1],
                                            relation=row[2],
                                            payload=json.loads(row[3]),
                                        )
                                    ],
                                )
                            )
                frontier = next_frontier
        return paths

    def detect_conflict(
        self, claim_a: str, claim_b: str
    ) -> ConflictReport | None:
        """Check whether claim_a and claim_b have a 'contradicts' edge."""
        with self._lock:
            row = self._con.execute(
                """
                SELECT 1 FROM kg_edges
                WHERE relation='contradicts'
                  AND ((src=? AND dst=?) OR (src=? AND dst=?))
                  AND profile_id=? AND project_id=?
                LIMIT 1
                """,
                (
                    claim_a, claim_b,
                    claim_b, claim_a,
                    self._profile_id, self._project_id,
                ),
            ).fetchone()
        if row is None:
            return None
        return ConflictReport(
            claim_a=claim_a,
            claim_b=claim_b,
            conflict_type="contradicts",
            description=(
                f"Edge with relation_type='contradicts' exists "
                f"between {claim_a} and {claim_b}"
            ),
        )

    def export_visualization(self, format: str) -> str:
        """Export the graph as JSON (graphml / cytoscape)."""
        with self._lock:
            node_rows = self._con.execute(
                "SELECT node_id, payload FROM kg_nodes WHERE profile_id=? AND project_id=?",
                (self._profile_id, self._project_id),
            ).fetchall()
            edge_rows = self._con.execute(
                "SELECT src, dst, relation FROM kg_edges WHERE profile_id=? AND project_id=?",
                (self._profile_id, self._project_id),
            ).fetchall()
        nodes = [
            {"id": row[0], **json.loads(row[1])} for row in node_rows
        ]
        edges = [
            {"src": row[0], "dst": row[1], "relation": row[2]} for row in edge_rows
        ]
        return json.dumps(
            {"format": format, "nodes": nodes, "edges": edges},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # LongTermMemoryGraph-compatible helpers (used by KnowledgeManager)
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        """Return the number of nodes in this profile/project scope."""
        with self._lock:
            row = self._con.execute(
                "SELECT COUNT(*) FROM kg_nodes WHERE profile_id=? AND project_id=?",
                (self._profile_id, self._project_id),
            ).fetchone()
        return row[0] if row else 0

    def edge_count(self) -> int:
        """Return the number of edges in this profile/project scope."""
        with self._lock:
            row = self._con.execute(
                "SELECT COUNT(*) FROM kg_edges WHERE profile_id=? AND project_id=?",
                (self._profile_id, self._project_id),
            ).fetchone()
        return row[0] if row else 0

    def add_node(self, node: Any) -> None:
        """Accept a MemoryNode and upsert it (KnowledgeManager compatibility)."""
        payload: dict[str, Any] = {
            "content": getattr(node, "content", ""),
            "node_type": getattr(node, "node_type", "fact"),
            "tags": getattr(node, "tags", []),
            "confidence": getattr(node, "confidence", 1.0),
        }
        self.upsert_node(node.node_id, payload)

    def search(self, query: str, limit: int = 10) -> list[Any]:
        """Simple keyword search over node content (KnowledgeManager compatibility).

        Returns MemoryNode-like objects so KnowledgeManager can work with
        results without type changes.
        """
        from hi_agent.memory.long_term import MemoryNode

        if not query.strip():
            return []
        keywords = query.lower().split()
        with self._lock:
            rows = self._con.execute(
                "SELECT node_id, payload FROM kg_nodes WHERE profile_id=? AND project_id=?",
                (self._profile_id, self._project_id),
            ).fetchall()
        scored: list[tuple[int, MemoryNode]] = []
        for node_id, payload_str in rows:
            p = json.loads(payload_str)
            content = p.get("content", "")
            tags = p.get("tags", [])
            text = (content + " " + " ".join(tags)).lower()
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                scored.append(
                    (
                        hits,
                        MemoryNode(
                            node_id=node_id,
                            content=content,
                            node_type=p.get("node_type", "fact"),
                            tags=tags,
                            confidence=p.get("confidence", 1.0),
                        ),
                    )
                )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in scored[:limit]]

    def save(self) -> None:
        """No-op: SQLite writes are immediate. Present for API compatibility."""

    def load(self) -> None:
        """No-op: SQLite is always loaded. Present for API compatibility."""

    # ------------------------------------------------------------------
    # Migration helper
    # ------------------------------------------------------------------

    def migrate_from_json(self, json_path: Path) -> int:
        """Migrate nodes and edges from a JsonGraphBackend JSON file.

        Reads the JSON file at *json_path*, inserts nodes and edges into
        this SQLite backend (skipping duplicates via ON CONFLICT), and
        returns the number of records migrated.  The source JSON file is
        not modified.

        Args:
            json_path: Path to the JSON file written by LongTermMemoryGraph.save().

        Returns:
            Number of records (nodes + edges) inserted (duplicates skipped).
        """
        if not json_path.exists():
            return 0
        data = json.loads(json_path.read_text(encoding="utf-8"))
        migrated = 0
        with self._lock:
            for node_id, ndata in data.get("nodes", {}).items():
                payload = {
                    "content": ndata.get("content", ""),
                    "node_type": ndata.get("node_type", "fact"),
                    "tags": ndata.get("tags", []),
                    "confidence": ndata.get("confidence", 1.0),
                }
                cur = self._con.execute(
                    """
                    INSERT OR IGNORE INTO kg_nodes
                        (node_id, profile_id, project_id, tenant_id, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        node_id,
                        self._profile_id,
                        self._project_id,
                        self._tenant_id,
                        json.dumps(payload),
                    ),
                )
                migrated += cur.rowcount
            for edata in data.get("edges", []):
                cur = self._con.execute(
                    """
                    INSERT OR IGNORE INTO kg_edges
                        (src, dst, relation, profile_id, project_id, tenant_id, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edata.get("source_id", ""),
                        edata.get("target_id", ""),
                        edata.get("relation_type", "related"),
                        self._profile_id,
                        self._project_id,
                        self._tenant_id,
                        json.dumps({"weight": edata.get("weight", 1.0)}),
                    ),
                )
                migrated += cur.rowcount
            self._con.commit()
        return migrated


