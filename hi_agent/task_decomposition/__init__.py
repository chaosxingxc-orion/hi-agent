"""Task decomposition engine for hi-agent.

Provides DAG-based task decomposition, execution, and feedback collection.
"""

from hi_agent.task_decomposition.dag import TaskDAG, TaskNode, TaskNodeState
from hi_agent.task_decomposition.decomposer import TaskDecomposer
from hi_agent.task_decomposition.executor import (
    DAGExecutor,
    DAGProgress,
    DAGResult,
    DAGStepResult,
)
from hi_agent.task_decomposition.feedback import (
    DecompositionFeedback,
    FeedbackRecord,
)

__all__ = [
    "DAGExecutor",
    "DAGProgress",
    "DAGResult",
    "DAGStepResult",
    "DecompositionFeedback",
    "FeedbackRecord",
    "TaskDAG",
    "TaskDecomposer",
    "TaskNode",
    "TaskNodeState",
]
