# hi_agent/task_mgmt/plan_types.py
"""Plan type definitions migrated from agent-kernel.

These types describe common graph topologies at a high level.
Use plan_to_graph() to convert any Plan into a TrajectoryGraph
that AsyncTaskScheduler can execute.

Types:
    SequentialPlan  — linear chain A→B→C
    ParallelPlan    — groups execute sequentially; nodes within a group run concurrently
    DependencyPlan  — explicit DAG with per-node declared dependencies
    SpeculativePlan — all candidates run concurrently; winner committed externally
"""
from __future__ import annotations

from dataclasses import dataclass

from hi_agent.trajectory.graph import TrajectoryGraph, TrajNode


@dataclass(frozen=True)
class SequentialPlan:
    """Linear chain: node_ids[0] → node_ids[1] → … → node_ids[-1]."""
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class DependencyNode:
    """One node in a DependencyPlan with explicit upstream dependencies."""
    node_id: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyPlan:
    """Arbitrary DAG with per-node declared dependencies."""
    nodes: tuple[DependencyNode, ...]


@dataclass(frozen=True)
class ParallelPlan:
    """Groups run sequentially; nodes within each group run concurrently."""
    groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class SpeculativePlan:
    """All candidates start simultaneously; no dependencies between them."""
    candidate_ids: tuple[str, ...]


AnyPlan = SequentialPlan | ParallelPlan | DependencyPlan | SpeculativePlan


def plan_to_graph(plan: AnyPlan) -> TrajectoryGraph:
    """Convert any Plan type to a TrajectoryGraph for AsyncTaskScheduler."""
    if isinstance(plan, SequentialPlan):
        return _sequential_to_graph(plan)
    if isinstance(plan, ParallelPlan):
        return _parallel_to_graph(plan)
    if isinstance(plan, DependencyPlan):
        return _dependency_to_graph(plan)
    if isinstance(plan, SpeculativePlan):
        return _speculative_to_graph(plan)
    raise TypeError(f"Unsupported plan type: {type(plan).__name__}")


def _sequential_to_graph(plan: SequentialPlan) -> TrajectoryGraph:
    """Run _sequential_to_graph."""
    g = TrajectoryGraph()
    for nid in plan.node_ids:
        g.add_node(TrajNode(node_id=nid, node_type="task"))
    for i in range(len(plan.node_ids) - 1):
        g.add_sequence(plan.node_ids[i], plan.node_ids[i + 1])
    return g


def _parallel_to_graph(plan: ParallelPlan) -> TrajectoryGraph:
    """Every node in groups[i+1] depends on every node in groups[i]."""
    g = TrajectoryGraph()
    prev_group: tuple[str, ...] = ()
    for group in plan.groups:
        for nid in group:
            g.add_node(TrajNode(node_id=nid, node_type="task"))
        for nid in group:
            for dep in prev_group:
                g.add_sequence(dep, nid)
        prev_group = group
    return g


def _dependency_to_graph(plan: DependencyPlan) -> TrajectoryGraph:
    """Run _dependency_to_graph."""
    g = TrajectoryGraph()
    for dn in plan.nodes:
        g.add_node(TrajNode(node_id=dn.node_id, node_type="task"))
    for dn in plan.nodes:
        for dep in dn.depends_on:
            g.add_sequence(dep, dn.node_id)
    return g


def _speculative_to_graph(plan: SpeculativePlan) -> TrajectoryGraph:
    """Run _speculative_to_graph."""
    g = TrajectoryGraph()
    for cid in plan.candidate_ids:
        g.add_node(TrajNode(node_id=cid, node_type="task"))
    # No edges — all candidates are independent entry nodes
    return g
