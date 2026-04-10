"""Task management system: scheduling, communication, observation, control."""

from hi_agent.task_mgmt.handle import TaskHandle, TaskStatus
from hi_agent.task_mgmt.monitor import RecoveryReport, TaskMonitor
from hi_agent.task_mgmt.notification import (
    TaskCommunicator,
    TaskNotification,
    TaskSignal,
)
from hi_agent.task_mgmt.reflection import ReflectionOrchestrator
from hi_agent.task_mgmt.reflection_bridge import ReflectionBridge, ReflectionContext
from hi_agent.task_mgmt.restart_policy import (
    RestartAction,
    RestartDecision,
    RestartPolicyEngine,
    TaskAttempt,
    TaskRestartPolicy,
)
from hi_agent.task_mgmt.scheduler import ScheduleResult, TaskScheduler

TaskAttemptRecord = TaskAttempt

__all__ = [
    "RecoveryReport",
    "ReflectionBridge",
    "ReflectionContext",
    "ReflectionOrchestrator",
    "RestartAction",
    "RestartDecision",
    "RestartPolicyEngine",
    "ScheduleResult",
    "TaskAttempt",
    "TaskAttemptRecord",
    "TaskCommunicator",
    "TaskHandle",
    "TaskMonitor",
    "TaskNotification",
    "TaskRestartPolicy",
    "TaskScheduler",
    "TaskSignal",
    "TaskStatus",
]
