"""Core DAG data structure for task decomposition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hi_agent.contracts import TaskContract


class TaskNodeState(Enum):
    """Lifecycle states of a task node within a DAG."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """A single node in the task DAG.

    Attributes:
        node_id: Unique identifier within the DAG.
        task_contract: Sub-task contract for this node.
        state: Current lifecycle state.
        dependencies: Node IDs this node depends on.
        dependents: Node IDs that depend on this node.
        result: Execution result payload, if completed.
        failure_reason: Human-readable failure description.
        retry_count: How many times this node has been retried.
        max_retries: Maximum retry attempts before permanent failure.
        rollback_policy: How to handle rollback on failure.
    """

    node_id: str
    task_contract: TaskContract
    state: TaskNodeState = TaskNodeState.PENDING
    dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    failure_reason: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    rollback_policy: str = "compensate"  # "none" | "compensate" | "cascade"


class TaskDAG:
    """Directed Acyclic Graph for task decomposition.

    Core operations:
    - add_node / add_edge (with cycle detection)
    - get_ready_nodes (nodes whose deps are all completed)
    - topological_sort
    - get_subgraph (extract independent sub-DAG for worker dispatch)
    - validate (check for cycles, orphans, unreachable terminals)
    """

    def __init__(self) -> None:
        """Initialize TaskDAG."""
        self._nodes: dict[str, TaskNode] = {}
        self._edges: dict[str, set[str]] = {}  # from -> set(to)

    @property
    def nodes(self) -> dict[str, TaskNode]:
        """Read-only access to the node map."""
        return dict(self._nodes)

    def add_node(self, node: TaskNode) -> None:
        """Add a task node to the DAG.

        Args:
            node: The task node to add.

        Raises:
            ValueError: If a node with the same ID already exists.
        """
        if node.node_id in self._nodes:
            raise ValueError(f"Node '{node.node_id}' already exists in DAG")
        self._nodes[node.node_id] = node
        self._edges.setdefault(node.node_id, set())

    def add_edge(self, from_id: str, to_id: str) -> None:
        """Add a dependency edge (from_id must complete before to_id starts).

        Args:
            from_id: Source node ID (dependency).
            to_id: Target node ID (dependent).

        Raises:
            ValueError: If either node doesn't exist or the edge would
                create a cycle.
        """
        if from_id not in self._nodes:
            raise ValueError(f"Source node '{from_id}' not in DAG")
        if to_id not in self._nodes:
            raise ValueError(f"Target node '{to_id}' not in DAG")

        # Tentatively add the edge and check for cycles.
        self._edges.setdefault(from_id, set())
        self._edges[from_id].add(to_id)

        if self.has_cycle():
            self._edges[from_id].discard(to_id)
            raise ValueError(
                f"Edge '{from_id}' -> '{to_id}' would create a cycle"
            )

        # Maintain bidirectional bookkeeping on the nodes.
        if to_id not in self._nodes[from_id].dependents:
            self._nodes[from_id].dependents.append(to_id)
        if from_id not in self._nodes[to_id].dependencies:
            self._nodes[to_id].dependencies.append(from_id)

    def get_node(self, node_id: str) -> TaskNode:
        """Return the node with the given ID.

        Raises:
            KeyError: If the node does not exist.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found in DAG")
        return self._nodes[node_id]

    def get_ready_nodes(self) -> list[TaskNode]:
        """Return nodes whose all dependencies are COMPLETED and node is PENDING."""
        ready: list[TaskNode] = []
        for node in self._nodes.values():
            if node.state != TaskNodeState.PENDING:
                continue
            all_deps_done = all(
                self._nodes[dep_id].state == TaskNodeState.COMPLETED
                for dep_id in node.dependencies
            )
            if all_deps_done:
                ready.append(node)
        return ready

    def mark_running(self, node_id: str) -> None:
        """Transition a node to RUNNING state.

        Raises:
            KeyError: If the node does not exist.
            ValueError: If the node is not in PENDING or READY state.
        """
        node = self.get_node(node_id)
        if node.state not in (TaskNodeState.PENDING, TaskNodeState.READY):
            raise ValueError(
                f"Cannot mark '{node_id}' as running from state {node.state.value}"
            )
        node.state = TaskNodeState.RUNNING

    def mark_completed(
        self, node_id: str, result: dict[str, Any] | None = None
    ) -> None:
        """Transition a node to COMPLETED state.

        Args:
            node_id: Node to mark complete.
            result: Optional result payload.

        Raises:
            KeyError: If the node does not exist.
            ValueError: If the node is not in RUNNING state.
        """
        node = self.get_node(node_id)
        if node.state != TaskNodeState.RUNNING:
            raise ValueError(
                f"Cannot mark '{node_id}' as completed from state {node.state.value}"
            )
        node.state = TaskNodeState.COMPLETED
        node.result = result

    def mark_failed(self, node_id: str, reason: str) -> None:
        """Transition a node to FAILED state.

        Args:
            node_id: Node to mark as failed.
            reason: Human-readable failure reason.

        Raises:
            KeyError: If the node does not exist.
            ValueError: If the node is not in RUNNING state.
        """
        node = self.get_node(node_id)
        if node.state != TaskNodeState.RUNNING:
            raise ValueError(
                f"Cannot mark '{node_id}' as failed from state {node.state.value}"
            )
        node.state = TaskNodeState.FAILED
        node.failure_reason = reason

    def topological_sort(self) -> list[str]:
        """Return a topological ordering of node IDs.

        Uses Kahn's algorithm.

        Raises:
            ValueError: If the DAG contains a cycle.
        """
        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        for _src, targets in self._edges.items():
            for tgt in targets:
                in_degree[tgt] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        queue.sort()  # deterministic ordering
        result: list[str] = []

        while queue:
            current = queue.pop(0)
            result.append(current)
            for tgt in sorted(self._edges.get(current, set())):
                in_degree[tgt] -= 1
                if in_degree[tgt] == 0:
                    queue.append(tgt)
            queue.sort()

        if len(result) != len(self._nodes):
            raise ValueError("DAG contains a cycle")
        return result

    def has_cycle(self) -> bool:
        """Return True if the DAG contains a cycle."""
        # DFS-based cycle detection.
        white, gray, black = 0, 1, 2
        color: dict[str, int] = dict.fromkeys(self._nodes, white)

        def _dfs(nid: str) -> bool:
            color[nid] = gray
            for tgt in self._edges.get(nid, set()):
                if color[tgt] == gray:
                    return True
                if color[tgt] == white and _dfs(tgt):
                    return True
            color[nid] = black
            return False

        return any(color[nid] == white and _dfs(nid) for nid in self._nodes)

    def get_subgraph(self, root_ids: list[str]) -> TaskDAG:
        """Extract a self-contained sub-DAG rooted at given nodes.

        Includes all transitive dependents of root_ids. The sub-DAG can
        operate independently (self-closing loop).

        Args:
            root_ids: Starting node IDs for the sub-DAG.

        Returns:
            A new TaskDAG containing only the relevant nodes and edges.

        Raises:
            KeyError: If any root_id is not in the DAG.
        """
        for rid in root_ids:
            if rid not in self._nodes:
                raise KeyError(f"Root node '{rid}' not found in DAG")

        # BFS to collect all transitive dependents.
        collected: set[str] = set()
        frontier = list(root_ids)
        while frontier:
            nid = frontier.pop(0)
            if nid in collected:
                continue
            collected.add(nid)
            for tgt in self._edges.get(nid, set()):
                if tgt not in collected:
                    frontier.append(tgt)

        sub = TaskDAG()
        for nid in collected:
            original = self._nodes[nid]
            clone = TaskNode(
                node_id=original.node_id,
                task_contract=original.task_contract,
                state=original.state,
                dependencies=[d for d in original.dependencies if d in collected],
                dependents=[d for d in original.dependents if d in collected],
                result=original.result,
                failure_reason=original.failure_reason,
                retry_count=original.retry_count,
                max_retries=original.max_retries,
                rollback_policy=original.rollback_policy,
            )
            sub._nodes[clone.node_id] = clone
            sub._edges[clone.node_id] = set()

        for src in collected:
            for tgt in self._edges.get(src, set()):
                if tgt in collected:
                    sub._edges[src].add(tgt)

        return sub

    def get_parallel_groups(self) -> list[list[str]]:
        """Return groups of nodes that can execute in parallel.

        Each group contains nodes at the same topological level. Within a
        group, nodes have no mutual dependencies and can run concurrently.
        """
        if not self._nodes:
            return []

        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        for _src, targets in self._edges.items():
            for tgt in targets:
                in_degree[tgt] += 1

        current_level = sorted(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        groups: list[list[str]] = []

        while current_level:
            groups.append(current_level)
            next_level: list[str] = []
            for nid in current_level:
                for tgt in sorted(self._edges.get(nid, set())):
                    in_degree[tgt] -= 1
                    if in_degree[tgt] == 0:
                        next_level.append(tgt)
            current_level = sorted(set(next_level))

        return groups

    def is_complete(self) -> bool:
        """True if all nodes are COMPLETED or SKIPPED."""
        terminal = {TaskNodeState.COMPLETED, TaskNodeState.SKIPPED}
        return all(n.state in terminal for n in self._nodes.values())

    def is_failed(self) -> bool:
        """True if any node is FAILED and not rolled back."""
        return any(
            n.state == TaskNodeState.FAILED for n in self._nodes.values()
        )

    def validate(self) -> list[str]:
        """Validate DAG integrity. Return list of issues (empty = valid).

        Checks performed:
        - Cycle detection
        - Orphan nodes (no edges at all and not the only node)
        - Dangling dependency references
        - Empty DAG
        """
        issues: list[str] = []

        if not self._nodes:
            issues.append("DAG has no nodes")
            return issues

        if self.has_cycle():
            issues.append("DAG contains a cycle")

        # Check dangling references in dependencies / dependents.
        for nid, node in self._nodes.items():
            for dep in node.dependencies:
                if dep not in self._nodes:
                    issues.append(
                        f"Node '{nid}' references unknown dependency '{dep}'"
                    )
            for dep in node.dependents:
                if dep not in self._nodes:
                    issues.append(
                        f"Node '{nid}' references unknown dependent '{dep}'"
                    )

        # Check for orphan nodes (connected to nothing, in a multi-node DAG).
        if len(self._nodes) > 1:
            for nid, _node in self._nodes.items():
                has_incoming = any(
                    nid in targets
                    for targets in self._edges.values()
                )
                has_outgoing = bool(self._edges.get(nid))
                if not has_incoming and not has_outgoing:
                    issues.append(f"Node '{nid}' is an orphan (no edges)")

        return issues
