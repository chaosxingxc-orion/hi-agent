"""Orchestration layer connecting TaskDecomposition to the run system."""

from hi_agent.orchestrator.parallel_dispatcher import ParallelDispatcher
from hi_agent.orchestrator.result_aggregator import ResultAggregator
from hi_agent.orchestrator.task_orchestrator import (
    OrchestratorResult,
    SubTaskResult,
    TaskOrchestrator,
)

__all__ = [
    "OrchestratorResult",
    "ParallelDispatcher",
    "ResultAggregator",
    "SubTaskResult",
    "TaskOrchestrator",
]
