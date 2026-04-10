"""Trajectory subsystem package."""

from hi_agent.trajectory.execution import (
    ExecutionResult,
    GraphExecutor,
    StepResult,
)
from hi_agent.trajectory.graph import (
    EdgeType,
    NodeState,
    TrajectoryGraph,
    TrajEdge,
    TrajNode,
)
from hi_agent.trajectory.greedy import GreedyOptimizer
from hi_agent.trajectory.stage_graph import (
    StageGraph,
    ValidationReport,
    build_default_trace_graph,
    default_trace_stage_graph,
)

__all__ = [
    "EdgeType",
    "ExecutionResult",
    "GraphExecutor",
    "GreedyOptimizer",
    "NodeState",
    "StageGraph",
    "StepResult",
    "TrajEdge",
    "TrajNode",
    "TrajectoryGraph",
    "ValidationReport",
    "build_default_trace_graph",
    "default_trace_stage_graph",
]
