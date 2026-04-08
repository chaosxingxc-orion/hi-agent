"""Middleware protocol with 5-phase lifecycle hooks.

Each middleware has 5 lifecycle phases:
  1. pre_create   -- before middleware instantiation (config/dependency injection)
  2. pre_execute  -- before process() (modify input, skip, add context)
  3. execute      -- core logic (process message)
  4. post_execute -- after process() (modify output, log metrics, side effects)
  5. pre_destroy  -- before teardown (cleanup resources, persist state, flush)

Hook actions (inspired by agent-core's FilterAction):
  CONTINUE -- proceed normally
  MODIFY   -- replace the message with a modified version
  SKIP     -- skip this middleware, pass message through unchanged
  BLOCK    -- stop the entire pipeline
  RETRY    -- re-execute this middleware (up to max_retries)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class HookAction(Enum):
    CONTINUE = "continue"
    MODIFY = "modify"
    SKIP = "skip"
    BLOCK = "block"
    RETRY = "retry"


class LifecyclePhase(Enum):
    PRE_CREATE = "pre_create"
    PRE_EXECUTE = "pre_execute"
    EXECUTE = "execute"
    POST_EXECUTE = "post_execute"
    PRE_DESTROY = "pre_destroy"


@dataclass
class HookResult:
    """Result from a lifecycle hook."""

    action: HookAction = HookAction.CONTINUE
    modified_message: MiddlewareMessage | None = None  # for MODIFY action
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MiddlewareMessage:
    """Structured message between middlewares. No raw LLM context shared."""

    source: str
    target: str
    msg_type: str       # perception_result, execution_plan, execution_result,
                        # evaluation_result, reflection, escalation
    payload: dict[str, Any]
    token_cost: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LifecycleHook:
    """A registered lifecycle hook."""

    phase: LifecyclePhase
    callback: Callable[[MiddlewareMessage, dict[str, Any]], HookResult]
    priority: int = 0        # higher = runs first
    name: str = ""
    once: bool = False       # execute only once then auto-remove
    max_retries: int = 3     # for RETRY action
    _executed: bool = False


# --- Result dataclasses ---

@dataclass
class Entity:
    """An extracted entity from perception."""

    entity_type: str    # person, date, number, code_block, url, etc
    value: str
    position: int = 0   # character position in input


@dataclass
class PerceptionResult:
    """Output of Perception middleware."""

    raw_text: str
    entities: list[Entity] = field(default_factory=list)
    summary: str | None = None
    modality: str = "text"  # text, image, audio, multimodal
    context: str = ""       # assembled session context
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """Output of Control middleware."""

    graph_json: dict[str, Any]  # TrajectoryGraph serialized
    node_resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    # node_id -> {skill_id, memory_query, knowledge_query, tools}
    total_nodes: int = 0
    estimated_cost: float = 0.0


@dataclass
class ExecutionResult:
    """Output of Execution middleware (per node)."""

    node_id: str
    output: Any = None
    evidence: list[str] = field(default_factory=list)
    tokens_used: int = 0
    success: bool = True
    error: str | None = None
    idempotency_key: str = ""


@dataclass
class EvaluationResult:
    """Output of Evaluation middleware."""

    node_id: str
    verdict: str = "pass"  # pass, retry, fail, escalate
    quality_score: float = 1.0
    feedback: str = ""
    retry_instruction: str | None = None
    retry_count: int = 0
    max_retries: int = 3


class Middleware(Protocol):
    """Protocol for all middlewares."""

    @property
    def name(self) -> str: ...

    def process(self, message: MiddlewareMessage) -> MiddlewareMessage: ...

    def on_create(self, config: dict[str, Any]) -> None:
        """Called during pre_create phase. Override for custom init."""
        ...

    def on_destroy(self) -> None:
        """Called during pre_destroy phase. Override for cleanup."""
        ...
