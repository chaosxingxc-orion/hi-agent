"""Long-term memory: persistent structured knowledge.

Uses a graph/tree data structure for structured knowledge storage.
Loaded on-demand by model via retrieval. Supports:
- Entity nodes with typed attributes
- Relation edges between entities
- Hierarchical categories (tree structure)
- Semantic search via keyword/tag matching
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hi_agent.memory.mid_term import DailySummary, MidTermMemoryStore


@dataclass
class MemoryNode:
    """A node in the long-term memory graph."""

    node_id: str
    content: str
    node_type: str = "fact"  # fact, method, rule, pattern, entity
    tags: list[str] = field(default_factory=list)
    source_sessions: list[str] = field(default_factory=list)
    confidence: float = 1.0
    access_count: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MemoryEdge:
    """A relation between two memory nodes."""

    source_id: str
    target_id: str
    relation_type: str  # "leads_to", "contradicts", "supports", "part_of", "derived_from"
    weight: float = 1.0


class LongTermMemoryGraph:
    """Graph-based long-term memory store.

    Stores knowledge as nodes + edges. Supports:
    - Add/update/remove nodes
    - Add/remove edges
    - Search by keyword, tag, type
    - Graph traversal (neighbors, paths)
    - Persistence to JSON file
    """

    def __init__(
        self,
        storage_path: str = ".hi_agent/memory/long_term/graph.json",
        profile_id: str = "",
        embedding_fn: Callable[[str], list[float]] | None = None,
        project_id: str = "",
        base_dir: str | None = None,
    ) -> None:
        """Initialize LongTermMemoryGraph.

        Args:
            storage_path: Default path to graph JSON file. Used as-is when
                profile_id and base_dir are both empty.
            profile_id: When non-empty, overrides the storage path to
                {storage_path_base}/memory/L3/{profile_id}/graph.json where
                storage_path_base is the parent-of-parent of storage_path.
            embedding_fn: Optional callable that maps a text string to a
                float vector.  When provided, ``search()`` uses cosine
                similarity instead of TF-IDF.
            project_id: When non-empty, appended as a directory component
                beneath the profile directory for per-project scoping.
            base_dir: When provided, used as the root directory instead of
                deriving the base from storage_path.  Typically a temp dir
                in tests.
        """
        self._project_id = project_id
        if base_dir is not None:
            # Explicit base_dir overrides storage_path derivation.
            root = Path(base_dir)
            if profile_id and project_id:
                resolved = root / "L3" / profile_id / project_id / "graph.json"
            elif profile_id:
                resolved = root / "L3" / profile_id / "graph.json"
            elif project_id:
                resolved = root / "L3" / project_id / "graph.json"
            else:
                resolved = root / "graph.json"
        elif profile_id:
            # storage_path default: {base}/memory/long_term/graph.json
            # profile_id path:      {base}/memory/L3/{profile_id}/graph.json
            # So storage_path_base is three levels above graph.json.
            base = Path(storage_path).parents[2]
            if project_id:
                resolved = base / "memory" / "L3" / profile_id / project_id / "graph.json"
            else:
                resolved = base / "memory" / "L3" / profile_id / "graph.json"
        else:
            resolved = Path(storage_path)
        self._storage_path = resolved
        self._nodes: dict[str, MemoryNode] = {}
        self._edges: list[MemoryEdge] = []
        self._adjacency: dict[str, list[str]] = {}  # node_id -> [connected_node_ids]
        self._embedding_fn = embedding_fn
        # TF-IDF index (in-memory only, rebuilt on load)
        self._tf: dict[str, dict[str, float]] = {}   # node_id -> {term: tf}
        self._df: dict[str, int] = {}                # term -> doc_count
        # Embedding cache (lazy, in-memory only)
        self._embeddings: dict[str, list[float]] = {}

        if self._storage_path.exists():
            self.load()

    # ------------------------------------------------------------------ CRUD

    def add_node(self, node: MemoryNode) -> None:
        """Add a node to the graph."""
        now = datetime.now(UTC).isoformat()
        if not node.created_at:
            node.created_at = now
        if not node.updated_at:
            node.updated_at = now
        self._nodes[node.node_id] = node
        if node.node_id not in self._adjacency:
            self._adjacency[node.node_id] = []
        self._index_node(node)

    def update_node(
        self,
        node_id: str,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Update an existing node's content and/or tags."""
        node = self._nodes.get(node_id)
        if node is None:
            return
        if content is not None:
            node.content = content
        if tags is not None:
            node.tags = tags
        node.updated_at = datetime.now(UTC).isoformat()

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its connected edges."""
        if node_id not in self._nodes:
            return
        self._unindex_node(node_id)
        del self._nodes[node_id]
        # Remove edges involving this node
        self._edges = [
            e
            for e in self._edges
            if e.source_id != node_id and e.target_id != node_id
        ]
        # Clean adjacency
        self._adjacency.pop(node_id, None)
        for nid in self._adjacency:
            self._adjacency[nid] = [
                n for n in self._adjacency[nid] if n != node_id
            ]
        # Remove cached embedding
        self._embeddings.pop(node_id, None)

    def add_edge(self, edge: MemoryEdge) -> None:
        """Add an edge between two nodes."""
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            return
        self._edges.append(edge)
        self._adjacency.setdefault(edge.source_id, []).append(edge.target_id)
        self._adjacency.setdefault(edge.target_id, []).append(edge.source_id)

    def remove_edge(self, source_id: str, target_id: str) -> None:
        """Remove all edges between source and target."""
        self._edges = [
            e
            for e in self._edges
            if not (e.source_id == source_id and e.target_id == target_id)
        ]
        if source_id in self._adjacency:
            self._adjacency[source_id] = [
                n for n in self._adjacency[source_id] if n != target_id
            ]
        if target_id in self._adjacency:
            self._adjacency[target_id] = [
                n for n in self._adjacency[target_id] if n != source_id
            ]

    # ------------------------------------------------------------------ Query

    def get_node(self, node_id: str) -> MemoryNode | None:
        """Retrieve a node by ID."""
        return self._nodes.get(node_id)

    def search(self, query: str, limit: int = 10) -> list[MemoryNode]:
        """Search nodes by semantic relevance.

        Ranking priority:
        1. If *embedding_fn* is set: cosine similarity between query and node
           embeddings (lazy-cached per node).
        2. If TF-IDF index is populated: TF-IDF weighted term scoring.
        3. Fallback: keyword hit count + access_count boost (original behaviour).
        """
        if not query.strip():
            return []

        scored: list[tuple[float, MemoryNode]] = []

        if self._embedding_fn is not None:
            # --- Embedding-based cosine similarity ---
            query_vec = self._embedding_fn(query)
            for node in self._nodes.values():
                if node.node_id not in self._embeddings:
                    self._embeddings[node.node_id] = self._embedding_fn(node.content)
                node_vec = self._embeddings[node.node_id]
                score = _cosine(query_vec, node_vec)
                if score > 0:
                    scored.append((score, node))
        elif self._tf:
            # --- TF-IDF scoring ---
            query_terms = query.lower().split()
            n_docs = len(self._nodes)
            for node in self._nodes.values():
                tf = self._tf.get(node.node_id, {})
                tfidf_score = sum(
                    tf.get(term, 0.0)
                    * math.log((n_docs + 1) / (self._df.get(term, 0) + 1))
                    for term in query_terms
                )
                # Keyword hit count as minimum signal when TF-IDF is zero
                # (can happen when n_docs is small and all docs contain the term)
                keyword_hits = sum(1 for term in query_terms if term in tf)
                score = tfidf_score + keyword_hits * 0.001
                if score > 0:
                    scored.append((score, node))
        else:
            # --- Keyword fallback ---
            keywords = query.lower().split()
            for node in self._nodes.values():
                text = (node.content + " " + " ".join(node.tags)).lower()
                hits = sum(1 for kw in keywords if kw in text)
                if hits > 0:
                    score = hits + node.access_count * 0.01
                    scored.append((score, node))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [node for _, node in scored[:limit]]

    def search_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryNode]:
        """Search for nodes containing any of the given tags."""
        tag_set = {t.lower() for t in tags}
        results: list[MemoryNode] = []
        for node in self._nodes.values():
            node_tags = {t.lower() for t in node.tags}
            if tag_set & node_tags:
                results.append(node)
                if len(results) >= limit:
                    break
        return results

    def search_by_type(self, node_type: str, limit: int = 10) -> list[MemoryNode]:
        """Search for nodes of a given type."""
        results: list[MemoryNode] = []
        for node in self._nodes.values():
            if node.node_type == node_type:
                results.append(node)
                if len(results) >= limit:
                    break
        return results

    def get_neighbors(
        self, node_id: str, relation_type: str | None = None
    ) -> list[MemoryNode]:
        """Get neighbor nodes, optionally filtered by relation type."""
        if node_id not in self._adjacency:
            return []

        if relation_type is None:
            neighbor_ids = set(self._adjacency[node_id])
        else:
            neighbor_ids: set[str] = set()
            for edge in self._edges:
                if edge.relation_type != relation_type:
                    continue
                if edge.source_id == node_id:
                    neighbor_ids.add(edge.target_id)
                elif edge.target_id == node_id:
                    neighbor_ids.add(edge.source_id)

        return [self._nodes[nid] for nid in neighbor_ids if nid in self._nodes]

    def get_subgraph(
        self, root_id: str, depth: int = 2
    ) -> tuple[list[MemoryNode], list[MemoryEdge]]:
        """BFS traversal from *root_id* up to *depth* hops."""
        if root_id not in self._nodes:
            return [], []

        visited: set[str] = {root_id}
        frontier: set[str] = {root_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                for neighbor_id in self._adjacency.get(nid, []):
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.add(neighbor_id)
            frontier = next_frontier
            if not frontier:
                break

        nodes = [self._nodes[nid] for nid in visited if nid in self._nodes]
        edges = [
            e
            for e in self._edges
            if e.source_id in visited and e.target_id in visited
        ]
        return nodes, edges

    # ------------------------------------------------------------------ Persistence

    def save(self) -> None:
        """Persist graph to JSON file."""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nodes": {nid: asdict(node) for nid, node in self._nodes.items()},
            "edges": [asdict(e) for e in self._edges],
        }
        self._storage_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def load(self) -> None:
        """Load graph from JSON file."""
        if not self._storage_path.exists():
            return
        data = json.loads(self._storage_path.read_text(encoding="utf-8"))

        self._nodes.clear()
        self._edges.clear()
        self._adjacency.clear()
        self._tf.clear()
        self._df.clear()
        self._embeddings.clear()

        for nid, ndata in data.get("nodes", {}).items():
            node = MemoryNode(
                node_id=ndata["node_id"],
                content=ndata.get("content", ""),
                node_type=ndata.get("node_type", "fact"),
                tags=ndata.get("tags", []),
                source_sessions=ndata.get("source_sessions", []),
                confidence=ndata.get("confidence", 1.0),
                access_count=ndata.get("access_count", 0),
                created_at=ndata.get("created_at", ""),
                updated_at=ndata.get("updated_at", ""),
            )
            self._nodes[nid] = node
            self._adjacency.setdefault(nid, [])

        for edata in data.get("edges", []):
            edge = MemoryEdge(
                source_id=edata["source_id"],
                target_id=edata["target_id"],
                relation_type=edata.get("relation_type", "related"),
                weight=edata.get("weight", 1.0),
            )
            self._edges.append(edge)
            self._adjacency.setdefault(edge.source_id, []).append(edge.target_id)
            self._adjacency.setdefault(edge.target_id, []).append(edge.source_id)

        self._rebuild_index()

    # ------------------------------------------------------------------ Stats

    def node_count(self) -> int:
        """Return number of nodes."""
        return len(self._nodes)

    def edge_count(self) -> int:
        """Return number of edges."""
        return len(self._edges)

    # ------------------------------------------------------------------ Access tracking

    def record_access(self, node_id: str) -> None:
        """Increment access_count when node is loaded into context."""
        node = self._nodes.get(node_id)
        if node is not None:
            node.access_count += 1

    # ------------------------------------------------------------------ Project scoping

    def list_runs_by_project(self, project_id: str) -> list[str]:
        """Return all run_ids recorded in nodes for the given project_id."""
        return list({
            src
            for node in self._nodes.values()
            for src in node.source_sessions
            if project_id and project_id in node.tags
        })

    # ------------------------------------------------------------------ Graph inference

    def find_transitive_closure(
        self,
        start_id: str,
        relation_type: str | None = None,
        max_depth: int = 5,
    ) -> set[str]:
        """BFS over edges of the given relation_type from start_id.

        Returns set of reachable node IDs (start_id itself is excluded).
        """
        visited: set[str] = set()
        queue = [start_id]
        depth = 0
        while queue and depth < max_depth:
            next_queue: list[str] = []
            for node_id in queue:
                for edge in self._edges:
                    if edge.source_id == node_id and node_id not in visited:
                        if relation_type is None or edge.relation_type == relation_type:
                            next_queue.append(edge.target_id)
                visited.add(node_id)
            queue = [n for n in next_queue if n not in visited]
            depth += 1
        visited.discard(start_id)
        return visited

    def find_conflicts(self, node_id: str) -> list[tuple[str, str]]:
        """Return (neighbor_id, relation_type) pairs where relation_type == 'contradicts'."""
        return [
            (e.target_id if e.source_id == node_id else e.source_id, e.relation_type)
            for e in self._edges
            if e.relation_type == "contradicts"
            and (e.source_id == node_id or e.target_id == node_id)
        ]

    def get_subgraph_with_confidence(
        self, root_id: str, max_depth: int = 3
    ) -> dict[str, Any]:
        """Return a subgraph dict with nodes and their confidence scores.

        Uses the existing get_subgraph() method for traversal and augments
        the result with per-node confidence and node_type metadata.
        """
        nodes, _edges = self.get_subgraph(root_id, max_depth)
        result: dict[str, Any] = {}
        for node in nodes:
            result[node.node_id] = {
                "content": node.content,
                "confidence": node.confidence,
                "node_type": node.node_type,
            }
        return result

    # ------------------------------------------------------------------ TF-IDF index

    def _index_node(self, node: MemoryNode) -> None:
        """Add node to TF-IDF index."""
        terms = node.content.lower().split()
        if not terms:
            return
        term_counts: dict[str, int] = {}
        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1
        tf: dict[str, float] = {
            term: count / len(terms) for term, count in term_counts.items()
        }
        self._tf[node.node_id] = tf
        for term in tf:
            self._df[term] = self._df.get(term, 0) + 1

    def _unindex_node(self, node_id: str) -> None:
        """Remove node from TF-IDF index."""
        tf = self._tf.pop(node_id, {})
        for term in tf:
            current = self._df.get(term, 0)
            if current <= 1:
                self._df.pop(term, None)
            else:
                self._df[term] = current - 1

    def _rebuild_index(self) -> None:
        """Rebuild TF-IDF index from all current nodes."""
        self._tf.clear()
        self._df.clear()
        for node in self._nodes.values():
            self._index_node(node)


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Returns 0 on zero-norm."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class LongTermConsolidator:
    """Consolidate mid-term memories into long-term graph.

    Runs periodically to:
    1. Extract entities and facts from daily summaries
    2. Create/update nodes in the graph
    3. Establish edges between related concepts
    4. Merge duplicate nodes
    """

    def __init__(
        self, mid_term_store: MidTermMemoryStore, graph: LongTermMemoryGraph
    ) -> None:
        """Initialize LongTermConsolidator."""
        self._mid_term = mid_term_store
        self._graph = graph

    def consolidate(self, days: int = 7) -> int:
        """Process recent daily summaries into graph. Returns nodes added/updated."""
        summaries = self._mid_term.list_recent(days=days)
        count = 0
        for summary in summaries:
            facts = self._extract_facts(summary)
            patterns = self._extract_patterns(summary)
            all_nodes = facts + patterns
            for node in all_nodes:
                self._graph.add_node(node)
                count += 1
            # Find and add relations
            edges = self._find_relations(all_nodes)
            for edge in edges:
                self._graph.add_edge(edge)
        # Merge duplicates at the end
        self._merge_duplicates()
        if count > 0:
            self._graph.save()   # persist to disk after consolidation
        return count

    def _extract_facts(self, summary: DailySummary) -> list[MemoryNode]:
        """Extract fact nodes from daily summary."""
        nodes: list[MemoryNode] = []
        for learning in summary.key_learnings:
            node = MemoryNode(
                node_id=_make_id(),
                content=learning,
                node_type="fact",
                tags=["learning", f"date:{summary.date}"],
                source_sessions=[],
                confidence=0.8,
            )
            nodes.append(node)
        # Tasks completed become fact nodes too
        for task in summary.tasks_completed:
            node = MemoryNode(
                node_id=_make_id(),
                content=f"Completed: {task}",
                node_type="fact",
                tags=["completed", f"date:{summary.date}"],
                confidence=1.0,
            )
            nodes.append(node)
        return nodes

    def _extract_patterns(self, summary: DailySummary) -> list[MemoryNode]:
        """Extract pattern nodes from observed patterns."""
        nodes: list[MemoryNode] = []
        for pattern in summary.patterns_observed:
            node = MemoryNode(
                node_id=_make_id(),
                content=pattern,
                node_type="pattern",
                tags=["pattern", f"date:{summary.date}"],
                confidence=0.7,
            )
            nodes.append(node)
        return nodes

    def _find_relations(self, nodes: list[MemoryNode]) -> list[MemoryEdge]:
        """Find relations between new and existing nodes.

        Uses simple keyword overlap to detect relations.
        """
        edges: list[MemoryEdge] = []
        # Check new nodes against existing graph nodes
        for new_node in nodes:
            new_words = set(new_node.content.lower().split())
            for existing_id, existing_node in self._graph._nodes.items():
                if existing_id == new_node.node_id:
                    continue
                existing_words = set(existing_node.content.lower().split())
                overlap = new_words & existing_words
                # Require meaningful overlap (exclude very short common words)
                meaningful = {w for w in overlap if len(w) > 3}
                if len(meaningful) >= 2:
                    relation = (
                        "supports"
                        if new_node.node_type == existing_node.node_type
                        else "derived_from"
                    )
                    edges.append(
                        MemoryEdge(
                            source_id=new_node.node_id,
                            target_id=existing_id,
                            relation_type=relation,
                            weight=len(meaningful) / max(len(new_words), 1),
                        )
                    )
        return edges

    def _merge_duplicates(self) -> int:
        """Merge nodes with very similar content. Returns merge count.

        Two nodes are considered duplicates if their lowercased content
        is identical after stripping whitespace.
        """
        content_map: dict[str, list[str]] = {}
        for nid, node in self._graph._nodes.items():
            key = node.content.strip().lower()
            content_map.setdefault(key, []).append(nid)

        merge_count = 0
        for _, node_ids in content_map.items():
            if len(node_ids) <= 1:
                continue
            # Keep the first, merge others into it
            keeper_id = node_ids[0]
            keeper = self._graph._nodes[keeper_id]
            for dup_id in node_ids[1:]:
                dup = self._graph._nodes.get(dup_id)
                if dup is None:
                    continue
                # Merge tags and source_sessions
                keeper.tags = list(set(keeper.tags) | set(dup.tags))
                keeper.source_sessions = list(
                    set(keeper.source_sessions) | set(dup.source_sessions)
                )
                keeper.access_count += dup.access_count
                keeper.confidence = max(keeper.confidence, dup.confidence)
                self._graph.remove_node(dup_id)
                merge_count += 1
        return merge_count


def _make_id() -> str:
    """Generate a short unique ID."""
    return uuid.uuid4().hex[:12]
