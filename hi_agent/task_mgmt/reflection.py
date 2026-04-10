"""ReflectionOrchestrator: wires ReflectionBridge output into an inference function.

Migrated from agent-kernel. Accepts a generic async inference callable instead
of a ReasoningLoop, making it usable with any LLM backend.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from hi_agent.task_mgmt.reflection_bridge import (
    ReflectionBridge,
    ReflectionContext,
    TaskDescriptor,
    reflection_context_to_recovery_dict,
)
from hi_agent.task_mgmt.restart_policy import TaskAttempt

_logger = logging.getLogger(__name__)


class ReflectionOrchestrator:
    """Coordinates ReflectionBridge then inference for reflect-and-retry cycles.

    Stateless; safe to share across concurrent reflect requests.

    Args:
        bridge: ReflectionBridge used to build the reflection context.
        inference_fn: Async callable that receives keyword arguments
            (``recovery_context``, ``run_id``, and any extra kwargs)
            and returns the model result.
    """

    def __init__(
        self,
        bridge: ReflectionBridge,
        inference_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        """Initialize ReflectionOrchestrator."""
        self._bridge = bridge
        self._inference_fn = inference_fn

    async def reflect_and_infer(
        self,
        *,
        descriptor: TaskDescriptor,
        attempts: list[TaskAttempt],
        run_id: str,
        **extra_kwargs: Any,
    ) -> Any:
        """Build reflection context and run one inference cycle.

        Steps:
        1. Build ``ReflectionContext`` from descriptor + attempt history.
        2. Convert to ``recovery_context`` dict.
        3. Call ``inference_fn(recovery_context=..., run_id=..., **extra)``.

        Args:
            descriptor: TaskDescriptor of the reflecting task.
            attempts: All recorded attempts (should all be failed/cancelled).
            run_id: Run id for the reflection turn.
            **extra_kwargs: Additional keyword arguments forwarded to inference_fn.

        Returns:
            Whatever the inference_fn returns.
        """
        ctx: ReflectionContext = self._bridge.build_context(descriptor, attempts)
        recovery_context = reflection_context_to_recovery_dict(ctx)

        _logger.info(
            "task.reflection_inference task_id=%s attempts=%d run_id=%s",
            descriptor.task_id,
            ctx.attempt_count,
            run_id,
        )

        result = await self._inference_fn(
            recovery_context=recovery_context,
            run_id=run_id,
            **extra_kwargs,
        )
        return result
