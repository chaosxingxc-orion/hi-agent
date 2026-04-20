"""Unified trajectory graph for task planning and execution.

Replaces fragmented StageGraph and TaskDAG with a single graph primitive
that supports multiple topology modes:
  - Chain: A->B->C (linear execution)
  - Tree: Root->{A,B,C} (hierarchical decomposition)
  - DAG: arbitrary directed acyclic graph (parallel paths)
  - General: supports conditional back-edges for retry/backtrack

Inspired by LangGraph (Pregel supersteps, conditional edges) and
agent-core (channel-based message passing), but pure Python with
zero external dependencies.

Key design:
  - Nodes are generic (carry any payload via TrajNode)
  - Edges are typed (sequence, branch, conditional, backtrack)
  - Dynamic modification during execution (add/remove nodes and edges)
  - Superstep execution model (process all ready nodes per step)
  - Mermaid serialization for LLM readability
  - JSON serialization for persistence
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeState(Enum):
    """NodeState class."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class EdgeType(Enum):
    """EdgeType class."""

    SEQUENCE = "sequence"  # normal flow A->B
    BRANCH = "branch"  # parallel split A->{B,C}
    CONDITIONAL = "conditional"  # A->B if condition, else A->C
    BACKTRACK = "backtrack"  # B->A (retry/loop)


@dataclass
class TrajNode:
    """A node in the trajectory graph."""

    node_id: str
    node_type: str = "task"  # stage, task, action, decision, checkpoint
    state: NodeState = NodeState.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
    # Execution metadata
    priority: int = 5  # 1=highest, 10=lowest
    cost_estimate: float = 0.0  # estimated token cost
    retry_count: int = 0
    max_retries: int = 2
    result: Any = None
    failure_reason: str | None = None


@dataclass
class TrajEdge:
    """An edge in the trajectory graph."""

    source: str
    target: str
    edge_type: EdgeType = EdgeType.SEQUENCE
    condition: Callable[[dict[str, Any]], bool] | None = None
    condition_desc: str = ""  # human-readable condition description
    weight: float = 1.0  # for path selection (lower = preferred)
    label: str = ""  # display label


class TrajectoryGraph:
    """Unified graph for trajectory planning.

    Supports chain, tree, DAG, and general graph with conditional back-edges.
    """

    def __init__(self, graph_id: str = "default") -> None:
        """Initialize TrajectoryGraph."""
        self.graph_id = graph_id
        self._nodes: dict[str, TrajNode] = {}
        self._edges: list[TrajEdge] = []
        self._forward: dict[str, list[TrajEdge]] = {}  # source -> [edges]
        self._backward: dict[str, list[TrajEdge]] = {}  # target -> [edges]
        self._entry_nodes: list[str] = []
        self._terminal_nodes: list[str] = []

    # --- Node CRUD (dynamic) ---

    def add_node(self, node: TrajNode) -> None:
        """Add a node. Updates entry/terminal tracking."""
        if node.node_id in self._nodes:
            raise ValueError(f"Node '{node.node_id}' already exists")
        self._nodes[node.node_id] = node
        self._forward.setdefault(node.node_id, [])
        self._backward.setdefault(node.node_id, [])
        self._rebuild_entry_terminal()

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its edges. Dynamic modification."""
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found")
        # Remove all edges involving this node.
        self._edges = [e for e in self._edges if e.source != node_id and e.target != node_id]
        # Rebuild forward/backward indexes from scratch.
        del self._nodes[node_id]
        self._forward.pop(node_id, None)
        self._backward.pop(node_id, None)
        # Clean references in other nodes' adjacency lists.
        for nid in self._nodes:
            self._forward[nid] = [e for e in self._forward.get(nid, []) if e.target != node_id]
            self._backward[nid] = [e for e in self._backward.get(nid, []) if e.source != node_id]
        self._rebuild_entry_terminal()

    def get_node(self, node_id: str) -> TrajNode | None:
        """Return node or None if not found."""
        return self._nodes.get(node_id)

    def update_node_state(
        self,
        node_id: str,
        state: NodeState,
        result: Any = None,
        failure_reason: str | None = None,
    ) -> None:
        """Update node execution state."""
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(f"Node '{node_id}' not found")
        node.state = state
        if result is not None:
            node.result = result
        if failure_reason is not None:
            node.failure_reason = failure_reason

    # --- Edge CRUD (dynamic) ---

    def add_edge(self, edge: TrajEdge) -> None:
        """Add an edge. Validates nodes exist. Updates adjacency indexes."""
        if edge.source not in self._nodes:
            raise ValueError(f"Source node '{edge.source}' not found")
        if edge.target not in self._nodes:
            raise ValueError(f"Target node '{edge.target}' not found")
        self._edges.append(edge)
        self._forward.setdefault(edge.source, []).append(edge)
        self._backward.setdefault(edge.target, []).append(edge)
        self._rebuild_entry_terminal()

    def add_sequence(self, source: str, target: str, label: str = "") -> None:
        """Convenience: add a SEQUENCE edge."""
        self.add_edge(
            TrajEdge(
                source=source,
                target=target,
                edge_type=EdgeType.SEQUENCE,
                label=label,
            )
        )

    def add_branch(self, source: str, targets: list[str]) -> None:
        """Convenience: add BRANCH edges (parallel split)."""
        for t in targets:
            self.add_edge(
                TrajEdge(
                    source=source,
                    target=t,
                    edge_type=EdgeType.BRANCH,
                )
            )

    def add_conditional(
        self,
        source: str,
        target: str,
        condition: Callable[[dict[str, Any]], bool],
        desc: str = "",
    ) -> None:
        """Convenience: add a CONDITIONAL edge."""
        self.add_edge(
            TrajEdge(
                source=source,
                target=target,
                edge_type=EdgeType.CONDITIONAL,
                condition=condition,
                condition_desc=desc,
            )
        )

    def add_backtrack(
        self,
        source: str,
        target: str,
        condition: Callable[[dict[str, Any]], bool] | None = None,
        desc: str = "",
    ) -> None:
        """Convenience: add a BACKTRACK edge (retry/loop)."""
        self.add_edge(
            TrajEdge(
                source=source,
                target=target,
                edge_type=EdgeType.BACKTRACK,
                condition=condition,
                condition_desc=desc,
            )
        )

    def remove_edge(self, source: str, target: str) -> None:
        """Remove first edge from source to target."""
        for i, e in enumerate(self._edges):
            if e.source == source and e.target == target:
                self._edges.pop(i)
                break
        else:
            raise KeyError(f"Edge '{source}' -> '{target}' not found")
        # Rebuild adjacency for affected nodes.
        self._forward[source] = [
            edge
            for edge in self._forward.get(source, [])
            if not (edge.source == source and edge.target == target)
        ]
        self._backward[target] = [
            edge
            for edge in self._backward.get(target, [])
            if not (edge.source == source and edge.target == target)
        ]
        self._rebuild_entry_terminal()

    def get_outgoing(self, node_id: str) -> list[TrajEdge]:
        """Return outgoing edges from node."""
        return list(self._forward.get(node_id, []))

    def get_incoming(self, node_id: str) -> list[TrajEdge]:
        """Return incoming edges to node."""
        return list(self._backward.get(node_id, []))

    # --- Query ---

    def get_ready_nodes(self) -> list[TrajNode]:
        """Nodes whose all SEQUENCE/BRANCH dependencies are COMPLETED and node is PENDING.

        For CONDITIONAL edges, evaluate condition against current graph state.
        """
        ready: list[TrajNode] = []
        graph_state = self._build_graph_state()
        for node in self._nodes.values():
            if node.state != NodeState.PENDING:
                continue
            deps = self._get_dependencies(node.node_id)
            if not deps:
                # No dependencies — check if there are conditional incoming edges.
                incoming = self._backward.get(node.node_id, [])
                conditional_incoming = [e for e in incoming if e.edge_type == EdgeType.CONDITIONAL]
                if conditional_incoming:
                    # At least one conditional must be satisfied.
                    any_met = any(
                        (e.condition is None or e.condition(graph_state))
                        and self._nodes[e.source].state == NodeState.COMPLETED
                        for e in conditional_incoming
                    )
                    if not any_met:
                        continue
                ready.append(node)
                continue
            # All non-conditional dependencies must be completed.
            all_done = all(self._nodes[dep_id].state == NodeState.COMPLETED for dep_id in deps)
            if not all_done:
                continue
            # Check conditional incoming edges.
            incoming_cond = [
                e
                for e in self._backward.get(node.node_id, [])
                if e.edge_type == EdgeType.CONDITIONAL
            ]
            if incoming_cond:
                any_met = any(
                    (e.condition is None or e.condition(graph_state))
                    and self._nodes[e.source].state == NodeState.COMPLETED
                    for e in incoming_cond
                )
                if not any_met:
                    continue
            ready.append(node)
        return ready

    def get_parallel_groups(self) -> list[list[str]]:
        """Return groups of nodes that can execute in parallel (topological levels)."""
        if not self._nodes:
            return []
        # Only consider SEQUENCE and BRANCH edges for levels.
        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        for e in self._edges:
            if e.edge_type in (EdgeType.SEQUENCE, EdgeType.BRANCH):
                in_degree[e.target] = in_degree.get(e.target, 0) + 1

        current_level = sorted(nid for nid, deg in in_degree.items() if deg == 0)
        groups: list[list[str]] = []
        while current_level:
            groups.append(current_level)
            next_level: list[str] = []
            for nid in current_level:
                for e in self._forward.get(nid, []):
                    if e.edge_type in (EdgeType.SEQUENCE, EdgeType.BRANCH):
                        in_degree[e.target] -= 1
                        if in_degree[e.target] == 0:
                            next_level.append(e.target)
            current_level = sorted(set(next_level))
        return groups

    def topological_sort(self) -> list[str]:
        """Topological ordering. Ignores BACKTRACK edges for sorting."""
        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        for e in self._edges:
            if e.edge_type != EdgeType.BACKTRACK:
                in_degree[e.target] = in_degree.get(e.target, 0) + 1

        queue = sorted(nid for nid, deg in in_degree.items() if deg == 0)
        result: list[str] = []
        while queue:
            current = queue.pop(0)
            result.append(current)
            for e in sorted(self._forward.get(current, []), key=lambda x: x.target):
                if e.edge_type != EdgeType.BACKTRACK:
                    in_degree[e.target] -= 1
                    if in_degree[e.target] == 0:
                        queue.append(e.target)
            queue.sort()

        if len(result) != len(self._nodes):
            raise ValueError("Graph contains a cycle (excluding backtrack edges)")
        return result

    def find_paths(
        self,
        source: str,
        target: str,
        max_paths: int = 5,
    ) -> list[list[str]]:
        """Find up to max_paths paths from source to target. DFS-based."""
        if source not in self._nodes or target not in self._nodes:
            return []
        paths: list[list[str]] = []

        def _dfs(current: str, path: list[str], visited: set[str]) -> None:
            if len(paths) >= max_paths:
                return
            if current == target:
                paths.append(list(path))
                return
            for e in self._forward.get(current, []):
                if e.target not in visited:
                    visited.add(e.target)
                    path.append(e.target)
                    _dfs(e.target, path, visited)
                    path.pop()
                    visited.discard(e.target)

        _dfs(source, [source], {source})
        return paths

    def get_subgraph(
        self,
        root_ids: list[str],
        depth: int = -1,
    ) -> TrajectoryGraph:
        """Extract a subgraph rooted at given nodes, optionally limited by depth."""
        collected: set[str] = set()
        frontier: list[tuple[str, int]] = [(rid, 0) for rid in root_ids]
        while frontier:
            nid, d = frontier.pop(0)
            if nid in collected:
                continue
            if nid not in self._nodes:
                continue
            if depth >= 0 and d > depth:
                continue
            collected.add(nid)
            for e in self._forward.get(nid, []):
                if e.target not in collected:
                    frontier.append((e.target, d + 1))

        sub = TrajectoryGraph(graph_id=f"{self.graph_id}_sub")
        for nid in collected:
            original = self._nodes[nid]
            clone = TrajNode(
                node_id=original.node_id,
                node_type=original.node_type,
                state=original.state,
                payload=dict(original.payload),
                priority=original.priority,
                cost_estimate=original.cost_estimate,
                retry_count=original.retry_count,
                max_retries=original.max_retries,
                result=original.result,
                failure_reason=original.failure_reason,
            )
            sub._nodes[clone.node_id] = clone
            sub._forward.setdefault(clone.node_id, [])
            sub._backward.setdefault(clone.node_id, [])

        for e in self._edges:
            if e.source in collected and e.target in collected:
                clone_edge = TrajEdge(
                    source=e.source,
                    target=e.target,
                    edge_type=e.edge_type,
                    condition=e.condition,
                    condition_desc=e.condition_desc,
                    weight=e.weight,
                    label=e.label,
                )
                sub._edges.append(clone_edge)
                sub._forward[e.source].append(clone_edge)
                sub._backward[e.target].append(clone_edge)

        sub._rebuild_entry_terminal()
        return sub

    def has_cycle(self, exclude_backtrack: bool = True) -> bool:
        """Detect cycles. By default excludes BACKTRACK edges (they're intentional)."""
        white, gray, black = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(self._nodes, white)

        def _dfs(nid: str) -> bool:
            color[nid] = gray
            for e in self._forward.get(nid, []):
                if exclude_backtrack and e.edge_type == EdgeType.BACKTRACK:
                    continue
                if color.get(e.target, white) == gray:
                    return True
                if color.get(e.target, white) == white and _dfs(e.target):
                    return True
            color[nid] = black
            return False

        return any(color[nid] == white and _dfs(nid) for nid in self._nodes)

    def get_critical_path(self) -> list[str]:
        """Find the longest path (critical path) through the graph.

        Uses topological order and dynamic programming on edge weights
        (cost_estimate of target node used as weight).
        """
        try:
            order = self.topological_sort()
        except ValueError:
            return []
        if not order:
            return []

        dist: dict[str, float] = dict.fromkeys(self._nodes, 0.0)
        prev: dict[str, str | None] = dict.fromkeys(self._nodes)

        for nid in order:
            for e in self._forward.get(nid, []):
                if e.edge_type == EdgeType.BACKTRACK:
                    continue
                target_cost = self._nodes[e.target].cost_estimate
                new_dist = dist[nid] + max(e.weight, target_cost if target_cost > 0 else e.weight)
                if new_dist > dist[e.target]:
                    dist[e.target] = new_dist
                    prev[e.target] = nid

        # Find the node with maximum distance.
        end_node = max(dist, key=lambda x: dist[x])
        # Reconstruct path.
        path: list[str] = []
        cur: str | None = end_node
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        return path

    @property
    def entry_nodes(self) -> list[str]:
        """Nodes with no incoming edges (excluding backtrack)."""
        return list(self._entry_nodes)

    @property
    def terminal_nodes(self) -> list[str]:
        """Nodes with no outgoing edges (excluding backtrack)."""
        return list(self._terminal_nodes)

    @property
    def node_count(self) -> int:
        """Return node_count."""
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        """Return edge_count."""
        return len(self._edges)

    # --- Evaluate conditional edges ---

    def evaluate_branches(self, node_id: str, state: dict[str, Any]) -> list[str]:
        """Evaluate all conditional outgoing edges from node_id.

        Returns list of target node_ids whose conditions are met.
        """
        targets: list[str] = []
        for e in self._forward.get(node_id, []):
            if e.edge_type == EdgeType.CONDITIONAL:
                if e.condition is None or e.condition(state):
                    targets.append(e.target)
            else:
                targets.append(e.target)
        return targets

    # --- Degenerate constructors ---

    @classmethod
    def as_chain(
        cls,
        node_ids: list[str],
        graph_id: str = "chain",
        payloads: dict[str, dict[str, Any]] | None = None,
    ) -> TrajectoryGraph:
        """Create a linear chain: A->B->C->D."""
        g = cls(graph_id=graph_id)
        for nid in node_ids:
            payload = (payloads or {}).get(nid, {})
            g.add_node(TrajNode(node_id=nid, node_type="stage", payload=payload))
        for i in range(len(node_ids) - 1):
            g.add_sequence(node_ids[i], node_ids[i + 1])
        return g

    @classmethod
    def as_tree(
        cls,
        root_id: str,
        children: dict[str, list[str]],
        graph_id: str = "tree",
    ) -> TrajectoryGraph:
        """Create a tree: root->{A,B}, A->{C,D}.

        children: parent_id -> [child_ids]
        """
        g = cls(graph_id=graph_id)
        # Collect all node IDs.
        all_ids: set[str] = {root_id}
        for parent, kids in children.items():
            all_ids.add(parent)
            all_ids.update(kids)
        for nid in sorted(all_ids):
            g.add_node(TrajNode(node_id=nid, node_type="task"))
        for parent, kids in children.items():
            g.add_branch(parent, kids)
        return g

    @classmethod
    def as_dag(
        cls,
        nodes: list[str],
        edges: list[tuple[str, str]],
        graph_id: str = "dag",
    ) -> TrajectoryGraph:
        """Create a DAG from node list and edge tuples."""
        g = cls(graph_id=graph_id)
        for nid in nodes:
            g.add_node(TrajNode(node_id=nid, node_type="task"))
        for src, tgt in edges:
            g.add_sequence(src, tgt)
        return g

    # --- Serialization ---

    def to_mermaid(self, title: str = "") -> str:
        """Serialize to Mermaid flowchart.

        Nodes colored by state: green=completed, yellow=running, red=failed, gray=pending.
        Conditional edges shown with condition_desc.
        Backtrack edges shown with dotted lines.
        """
        lines: list[str] = []
        if title:
            lines.append("---")
            lines.append(f"title: {title}")
            lines.append("---")
        lines.append("flowchart TD")

        state_styles = {
            NodeState.COMPLETED: "fill:#90EE90",
            NodeState.RUNNING: "fill:#FFD700",
            NodeState.FAILED: "fill:#FF6B6B",
            NodeState.SKIPPED: "fill:#D3D3D3",
            NodeState.PENDING: "fill:#E8E8E8",
            NodeState.READY: "fill:#87CEEB",
            NodeState.BLOCKED: "fill:#FFA07A",
        }

        for node in self._nodes.values():
            label = f"{node.node_id}[{node.node_id}: {node.state.value}]"
            lines.append(f"    {label}")

        for e in self._edges:
            if e.edge_type == EdgeType.BACKTRACK:
                arrow = f"-. {e.condition_desc or 'backtrack'} .->"
            elif e.edge_type == EdgeType.CONDITIONAL:
                arrow = f"-- {e.condition_desc or 'if?'} -->"
            elif e.label:
                arrow = f"-- {e.label} -->"
            else:
                arrow = "-->"
            lines.append(f"    {e.source} {arrow} {e.target}")

        # Style nodes by state.
        for node in self._nodes.values():
            style = state_styles.get(node.state, "fill:#E8E8E8")
            lines.append(f"    style {node.node_id} {style}")

        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for persistence."""
        return {
            "graph_id": self.graph_id,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "state": n.state.value,
                    "payload": n.payload,
                    "priority": n.priority,
                    "cost_estimate": n.cost_estimate,
                    "retry_count": n.retry_count,
                    "max_retries": n.max_retries,
                    "result": n.result,
                    "failure_reason": n.failure_reason,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "edge_type": e.edge_type.value,
                    "condition_desc": e.condition_desc,
                    "weight": e.weight,
                    "label": e.label,
                }
                for e in self._edges
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TrajectoryGraph:
        """Restore from JSON. Note: condition callables are NOT restored (set to None)."""
        g = cls(graph_id=data.get("graph_id", "default"))
        for nd in data.get("nodes", []):
            node = TrajNode(
                node_id=nd["node_id"],
                node_type=nd.get("node_type", "task"),
                state=NodeState(nd.get("state", "pending")),
                payload=nd.get("payload", {}),
                priority=nd.get("priority", 5),
                cost_estimate=nd.get("cost_estimate", 0.0),
                retry_count=nd.get("retry_count", 0),
                max_retries=nd.get("max_retries", 2),
                result=nd.get("result"),
                failure_reason=nd.get("failure_reason"),
            )
            g.add_node(node)
        for ed in data.get("edges", []):
            edge = TrajEdge(
                source=ed["source"],
                target=ed["target"],
                edge_type=EdgeType(ed.get("edge_type", "sequence")),
                condition=None,
                condition_desc=ed.get("condition_desc", ""),
                weight=ed.get("weight", 1.0),
                label=ed.get("label", ""),
            )
            g.add_edge(edge)
        return g

    def to_planning_prompt(self) -> str:
        """Generate a prompt section for LLM trajectory planning.

        Shows current graph state, ready nodes, completed nodes, available paths.
        """
        lines: list[str] = ["## Current Trajectory State", ""]

        completed = [n.node_id for n in self._nodes.values() if n.state == NodeState.COMPLETED]
        running = [n.node_id for n in self._nodes.values() if n.state == NodeState.RUNNING]
        failed = [n.node_id for n in self._nodes.values() if n.state == NodeState.FAILED]
        ready = [n.node_id for n in self.get_ready_nodes()]
        pending = [
            n.node_id
            for n in self._nodes.values()
            if n.state == NodeState.PENDING and n.node_id not in ready
        ]

        lines.append(f"- Completed: {', '.join(completed) if completed else 'none'}")
        lines.append(f"- Running: {', '.join(running) if running else 'none'}")
        lines.append(f"- Failed: {', '.join(failed) if failed else 'none'}")
        lines.append(f"- Ready (can execute now): {', '.join(ready) if ready else 'none'}")
        lines.append(f"- Pending: {', '.join(pending) if pending else 'none'}")
        lines.append("")

        lines.append("### Graph Structure")
        for e in self._edges:
            etype = e.edge_type.value
            desc = f" ({e.condition_desc})" if e.condition_desc else ""
            lines.append(f"  {e.source} --[{etype}{desc}]--> {e.target}")

        return "\n".join(lines)

    @classmethod
    def from_llm_plan(
        cls,
        plan: dict[str, Any],
        graph_id: str = "llm_plan",
    ) -> TrajectoryGraph:
        """Build graph from LLM-generated plan JSON.

        Expected format:
            {"nodes": [{"id": "...", "type": "...", "payload": {...}}],
             "edges": [{"source": "...", "target": "...", "type": "sequence"}]}
        """
        g = cls(graph_id=graph_id)
        for nd in plan.get("nodes", []):
            node = TrajNode(
                node_id=nd["id"],
                node_type=nd.get("type", "task"),
                payload=nd.get("payload", {}),
            )
            g.add_node(node)
        for ed in plan.get("edges", []):
            edge = TrajEdge(
                source=ed["source"],
                target=ed["target"],
                edge_type=EdgeType(ed.get("type", "sequence")),
            )
            g.add_edge(edge)
        return g

    # --- Execution helpers ---

    def step(
        self,
        execute_fn: Callable[[TrajNode], Any] | None = None,
    ) -> list[str]:
        """Execute one superstep: find ready nodes, execute them, update state.

        Returns list of executed node_ids.
        """
        ready = self.get_ready_nodes()
        executed: list[str] = []
        for node in ready:
            node.state = NodeState.RUNNING
            if execute_fn is not None:
                try:
                    result = execute_fn(node)
                    node.state = NodeState.COMPLETED
                    node.result = result
                except Exception as exc:
                    node.state = NodeState.FAILED
                    node.failure_reason = str(exc)
            else:
                node.state = NodeState.COMPLETED
            executed.append(node.node_id)

        # Evaluate backtrack edges for failed nodes.
        for node in self._nodes.values():
            if node.state == NodeState.FAILED:
                for e in self._forward.get(node.node_id, []):
                    if e.edge_type == EdgeType.BACKTRACK:
                        target_node = self._nodes.get(e.target)
                        if target_node and target_node.retry_count < target_node.max_retries:
                            should_backtrack = True
                            if e.condition is not None:
                                should_backtrack = e.condition(self._build_graph_state())
                            if should_backtrack:
                                target_node.state = NodeState.PENDING
                                target_node.retry_count += 1

        return executed

    def run_to_completion(
        self,
        execute_fn: Callable[[TrajNode], Any] | None = None,
        max_steps: int = 100,
    ) -> bool:
        """Run supersteps until all terminal nodes complete or max_steps reached.

        Returns True if completed, False if max_steps exceeded.
        """
        for _ in range(max_steps):
            executed = self.step(execute_fn)
            if not executed:
                break
            # Check if all terminal nodes are done.
            all_terminal_done = all(
                self._nodes[tid].state in (NodeState.COMPLETED, NodeState.SKIPPED, NodeState.FAILED)
                for tid in self._terminal_nodes
                if tid in self._nodes
            )
            if all_terminal_done and self._terminal_nodes:
                return True
        # Check final state.
        if not self._terminal_nodes:
            return all(
                n.state in (NodeState.COMPLETED, NodeState.SKIPPED, NodeState.FAILED)
                for n in self._nodes.values()
            )
        return all(
            self._nodes[tid].state in (NodeState.COMPLETED, NodeState.SKIPPED, NodeState.FAILED)
            for tid in self._terminal_nodes
            if tid in self._nodes
        )

    def prune_node(self, node_id: str, reason: str = "pruned") -> None:
        """Mark a node and all its dependents as SKIPPED."""
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(f"Node '{node_id}' not found")
        node.state = NodeState.SKIPPED
        node.failure_reason = reason
        # Propagate to all downstream nodes (excluding backtrack targets).
        queue: deque[str] = deque()
        for e in self._forward.get(node_id, []):
            if e.edge_type != EdgeType.BACKTRACK:
                queue.append(e.target)
        visited: set[str] = {node_id}
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            dep_node = self._nodes.get(nid)
            if dep_node and dep_node.state not in (NodeState.COMPLETED,):
                dep_node.state = NodeState.SKIPPED
                dep_node.failure_reason = f"upstream {node_id} {reason}"
                for e in self._forward.get(nid, []):
                    if e.edge_type != EdgeType.BACKTRACK:
                        queue.append(e.target)

    # --- Internal helpers ---

    def _rebuild_entry_terminal(self) -> None:
        """Recalculate entry/terminal node lists after modification."""
        has_incoming: set[str] = set()
        has_outgoing: set[str] = set()
        for e in self._edges:
            if e.edge_type != EdgeType.BACKTRACK:
                has_incoming.add(e.target)
                has_outgoing.add(e.source)
        self._entry_nodes = sorted(nid for nid in self._nodes if nid not in has_incoming)
        self._terminal_nodes = sorted(nid for nid in self._nodes if nid not in has_outgoing)

    def _get_dependencies(self, node_id: str) -> set[str]:
        """Get all nodes that must complete before this node can run.

        Only considers SEQUENCE and BRANCH edges (not BACKTRACK).
        """
        deps: set[str] = set()
        for e in self._backward.get(node_id, []):
            if e.edge_type in (EdgeType.SEQUENCE, EdgeType.BRANCH):
                deps.add(e.source)
        return deps

    def _build_graph_state(self) -> dict[str, Any]:
        """Build a state dict for condition evaluation."""
        return {
            "nodes": {
                nid: {
                    "state": n.state.value,
                    "result": n.result,
                    "retry_count": n.retry_count,
                }
                for nid, n in self._nodes.items()
            },
            "graph_id": self.graph_id,
        }
