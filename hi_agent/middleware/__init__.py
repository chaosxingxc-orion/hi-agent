"""Middleware subsystem: four-middleware architecture with 5-phase lifecycle."""

from hi_agent.middleware.protocol import (
    Entity,
    EvaluationResult,
    ExecutionPlan,
    ExecutionResult,
    HookAction,
    HookResult,
    LifecycleHook,
    LifecyclePhase,
    Middleware,
    MiddlewareMessage,
    PerceptionResult,
)
from hi_agent.middleware.perception import PerceptionMiddleware
from hi_agent.middleware.control import ControlMiddleware
from hi_agent.middleware.execution import ExecutionMiddleware
from hi_agent.middleware.evaluation import EvaluationMiddleware
from hi_agent.middleware.orchestrator import MiddlewareOrchestrator
from hi_agent.middleware.defaults import create_default_orchestrator

__all__ = [
    "Entity",
    "EvaluationMiddleware",
    "EvaluationResult",
    "ExecutionMiddleware",
    "ExecutionPlan",
    "ExecutionResult",
    "HookAction",
    "HookResult",
    "LifecycleHook",
    "LifecyclePhase",
    "Middleware",
    "MiddlewareMessage",
    "MiddlewareOrchestrator",
    "PerceptionMiddleware",
    "PerceptionResult",
    "ControlMiddleware",
    "create_default_orchestrator",
]
