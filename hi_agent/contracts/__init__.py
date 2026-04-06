"""Public contracts API for hi-agent.

This package exposes stable imports for spike and MVP code while allowing
internal schema split across focused modules.
"""

from hi_agent.contracts.branch import BranchState
from hi_agent.contracts.config import TaskFamilyConfig
from hi_agent.contracts.cts_budget import CTSBudget, CTSBudgetTemplate, CTSExplorationBudget
from hi_agent.contracts.identity import deterministic_id
from hi_agent.contracts.memory import RunIndex, StageSummary
from hi_agent.contracts.policy import PolicyVersionSet, SkillContentSpec
from hi_agent.contracts.requests import (
    ApprovalRequest,
    BranchStateUpdateRequest,
    HumanGateRequest,
    KernelManifest,
    OpenBranchRequest,
    QueryRunResponse,
    SignalRunRequest,
    StartRunRequest,
    StartRunResponse,
    TraceRuntimeView,
)
from hi_agent.contracts.run import RunState
from hi_agent.contracts.stage import StageState
from hi_agent.contracts.task import TaskBudget, TaskContract
from hi_agent.contracts.trajectory import NodeState, NodeType, TrajectoryNode

__all__ = [
    "ApprovalRequest",
    "BranchState",
    "BranchStateUpdateRequest",
    "CTSBudget",
    "CTSBudgetTemplate",
    "CTSExplorationBudget",
    "HumanGateRequest",
    "KernelManifest",
    "NodeState",
    "NodeType",
    "OpenBranchRequest",
    "PolicyVersionSet",
    "QueryRunResponse",
    "RunIndex",
    "RunState",
    "SignalRunRequest",
    "SkillContentSpec",
    "StageState",
    "StageSummary",
    "StartRunRequest",
    "StartRunResponse",
    "TaskBudget",
    "TaskContract",
    "TaskFamilyConfig",
    "TraceRuntimeView",
    "TrajectoryNode",
    "deterministic_id",
]
