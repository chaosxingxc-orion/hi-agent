"""Fine-grained Execution Hooks for hi-agent.

Provides 4 hook points around LLM calls and tool executions:
  - pre_llm_call: called before LLM API request (can transform request)
  - post_llm_call: called after LLM API response (can observe/transform response)
  - pre_tool: called before tool execution (can transform input)
  - post_tool: called after tool execution (can observe/transform result)

Design:
- Hook failures are isolated (one hook failing doesn't stop others)
- Hooks run in registration order
- Supports both sync and async hooks
- Built-in hooks: LLMCostLoggerHook, ToolResultSizeHook
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from hi_agent.llm import LLMRequest, LLMResponse
from hi_agent.observability.metric_counter import Counter

logger = logging.getLogger(__name__)
_hooks_errors_total = Counter("hi_agent_middleware_hooks_errors_total")

# ---------------------------------------------------------------------------
# Hook event identifiers
# ---------------------------------------------------------------------------


class HookEvent(StrEnum):
    """Enumeration of fine-grained hook points."""

    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"


# ---------------------------------------------------------------------------
# Context / Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LLMCallContext:
    """Carries contextual metadata into pre/post LLM hooks."""

    run_id: str
    stage_id: str | None
    turn_number: int
    request: LLMRequest
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCallResult:
    """Result produced after an LLM call, passed to post_llm hooks."""

    context: LLMCallContext
    response: LLMResponse
    duration_ms: float
    error: Exception | None = None


@dataclass
class ToolCallContext:
    """Carries contextual metadata into pre/post tool hooks."""

    run_id: str
    stage_id: str | None
    tool_name: str
    tool_input: dict[str, Any]
    turn_number: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResult:
    """Result produced after a tool execution, passed to post_tool hooks."""

    context: ToolCallContext
    result: str
    duration_ms: float
    error: Exception | None = None


# ---------------------------------------------------------------------------
# Hook type aliases
# ---------------------------------------------------------------------------

PreLLMHook = Callable[[LLMCallContext], "Awaitable[LLMCallContext] | LLMCallContext"]
PostLLMHook = Callable[[LLMCallResult], "Awaitable[LLMCallResult] | LLMCallResult"]
PreToolHook = Callable[[ToolCallContext], "Awaitable[ToolCallContext] | ToolCallContext"]
PostToolHook = Callable[[ToolCallResult], "Awaitable[ToolCallResult] | ToolCallResult"]

# ---------------------------------------------------------------------------
# HookChain
# ---------------------------------------------------------------------------


class HookChain:
    """Ordered chain of hooks for a single HookEvent.

    Hooks execute in registration order. A hook that raises an exception is
    logged as a warning and skipped; remaining hooks in the chain continue.
    Both synchronous and asynchronous hooks are supported.
    """

    def __init__(self, name: str, event: HookEvent) -> None:
        self.name = name
        self.event = event
        self._hooks: list[Callable[..., Any]] = []

    def register(self, hook: Callable[..., Any]) -> None:
        """Append a hook function to this chain."""
        self._hooks.append(hook)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call(self, hook: Callable[..., Any], arg: Any) -> Any:
        """Invoke a hook (sync or async) and return its result."""
        if inspect.iscoroutinefunction(hook):
            return await hook(arg)
        return hook(arg)

    # ------------------------------------------------------------------
    # Public run methods
    # ------------------------------------------------------------------

    async def run_pre_llm(self, ctx: LLMCallContext) -> LLMCallContext:
        """Run all pre_llm hooks in order, passing output to the next hook."""
        current = ctx
        for hook in self._hooks:
            try:
                result = await self._call(hook, current)
                if result is not None:
                    current = result
            except Exception as exc:
                _hooks_errors_total.inc()
                logger.warning(
                    "HookChain[%s/%s] pre_llm hook %r raised %s; skipping.",
                    self.name,
                    self.event,
                    getattr(hook, "__name__", hook),
                    exc,
                )
        return current

    async def run_post_llm(self, result: LLMCallResult) -> LLMCallResult:
        """Run all post_llm hooks in order, passing output to the next hook."""
        current = result
        for hook in self._hooks:
            try:
                out = await self._call(hook, current)
                if out is not None:
                    current = out
            except Exception as exc:
                _hooks_errors_total.inc()
                logger.warning(
                    "HookChain[%s/%s] post_llm hook %r raised %s; skipping.",
                    self.name,
                    self.event,
                    getattr(hook, "__name__", hook),
                    exc,
                )
        return current

    async def run_pre_tool(self, ctx: ToolCallContext) -> ToolCallContext:
        """Run all pre_tool hooks in order, passing output to the next hook."""
        current = ctx
        for hook in self._hooks:
            try:
                result = await self._call(hook, current)
                if result is not None:
                    current = result
            except Exception as exc:
                _hooks_errors_total.inc()
                logger.warning(
                    "HookChain[%s/%s] pre_tool hook %r raised %s; skipping.",
                    self.name,
                    self.event,
                    getattr(hook, "__name__", hook),
                    exc,
                )
        return current

    async def run_post_tool(self, result: ToolCallResult) -> ToolCallResult:
        """Run all post_tool hooks in order, passing output to the next hook."""
        current = result
        for hook in self._hooks:
            try:
                out = await self._call(hook, current)
                if out is not None:
                    current = out
            except Exception as exc:
                _hooks_errors_total.inc()
                logger.warning(
                    "HookChain[%s/%s] post_tool hook %r raised %s; skipping.",
                    self.name,
                    self.event,
                    getattr(hook, "__name__", hook),
                    exc,
                )
        return current

    def __len__(self) -> int:
        return len(self._hooks)


# ---------------------------------------------------------------------------
# HookRegistry
# ---------------------------------------------------------------------------


class HookRegistry:
    """Registry of hooks grouped by HookEvent.

    Not a global singleton by default — pass an instance around so that
    different subsystems (e.g., tests) can use independent registries.
    """

    def __init__(self) -> None:
        self._chains: dict[HookEvent, HookChain] = {
            event: HookChain(name=event.value, event=event) for event in HookEvent
        }

    def register(
        self,
        event: HookEvent,
        hook: Callable[..., Any],
        name: str = "",
    ) -> None:
        """Register *hook* for the given *event*.

        Args:
            event: One of the four HookEvent values.
            hook: A callable (sync or async) compatible with the event's
                  expected signature.
            name: Optional human-readable label (currently unused; reserved
                  for future per-hook metadata).
        """
        self._chains[event].register(hook)

    def get_chain(self, event: HookEvent) -> HookChain:
        """Return the HookChain for *event*."""
        return self._chains[event]

    def clear(self, event: HookEvent | None = None) -> None:
        """Remove all registered hooks.

        Args:
            event: If given, clears only that event's chain.
                   If ``None``, clears all chains.
        """
        if event is None:
            for ev in HookEvent:
                self._chains[ev] = HookChain(name=ev.value, event=ev)
        else:
            self._chains[event] = HookChain(name=event.value, event=event)


# ---------------------------------------------------------------------------
# ExecutionHookManager
# ---------------------------------------------------------------------------


class ExecutionHookManager:
    """High-level interface used by the Runner to wrap LLM and tool calls.

    Orchestrates pre→call→post sequences for both LLM and tool invocations,
    measures duration, and ensures post hooks are executed even when the
    underlying call raises an exception.
    """

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry

    async def wrap_llm_call(
        self,
        ctx: LLMCallContext,
        call_fn: Callable[[LLMRequest], Awaitable[LLMResponse]],
    ) -> LLMCallResult:
        """Execute pre_llm chain → call_fn → post_llm chain.

        Args:
            ctx: Initial LLM call context.
            call_fn: Async (or sync) callable that accepts an LLMRequest and
                     returns an LLMResponse.

        Returns:
            LLMCallResult from the post_llm chain.

        Raises:
            The exception from call_fn, after the post_llm chain has run.
        """
        pre_chain = self._registry.get_chain(HookEvent.PRE_LLM_CALL)
        post_chain = self._registry.get_chain(HookEvent.POST_LLM_CALL)

        ctx = await pre_chain.run_pre_llm(ctx)

        start_ns = time.perf_counter_ns()
        error: Exception | None = None
        response: LLMResponse | None = None

        try:
            if inspect.iscoroutinefunction(call_fn):
                response = await call_fn(ctx.request)
            else:
                response = call_fn(ctx.request)  # type: ignore[assignment]  expiry_wave: permanent
        except Exception as exc:
            _hooks_errors_total.inc()
            error = exc
        finally:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        if error is not None:
            # Build a minimal result so post hooks can observe the failure.
            from hi_agent.llm import TokenUsage

            dummy_response = LLMResponse(
                content="",
                model="unknown",
                usage=TokenUsage(),
                finish_reason="error",
            )
            err_result = LLMCallResult(
                context=ctx,
                response=dummy_response,
                duration_ms=duration_ms,
                error=error,
            )
            await post_chain.run_post_llm(err_result)
            raise error

        llm_result = LLMCallResult(
            context=ctx,
            response=response,  # type: ignore[arg-type]  expiry_wave: permanent
            duration_ms=duration_ms,
        )
        return await post_chain.run_post_llm(llm_result)

    async def wrap_tool_call(
        self,
        ctx: ToolCallContext,
        call_fn: Callable[[ToolCallContext], Awaitable[str]],
    ) -> ToolCallResult:
        """Execute pre_tool chain → call_fn → post_tool chain.

        Args:
            ctx: Initial tool call context.
            call_fn: Async (or sync) callable that accepts a ToolCallContext
                     and returns a string result.

        Returns:
            ToolCallResult from the post_tool chain.

        Raises:
            The exception from call_fn, after the post_tool chain has run.
        """
        pre_chain = self._registry.get_chain(HookEvent.PRE_TOOL)
        post_chain = self._registry.get_chain(HookEvent.POST_TOOL)

        ctx = await pre_chain.run_pre_tool(ctx)

        start_ns = time.perf_counter_ns()
        error: Exception | None = None
        result_str: str = ""

        try:
            if inspect.iscoroutinefunction(call_fn):
                result_str = await call_fn(ctx)
            else:
                result_str = call_fn(ctx)  # type: ignore[assignment]  expiry_wave: permanent
        except Exception as exc:
            _hooks_errors_total.inc()
            error = exc
        finally:
            duration_ms = (time.perf_counter_ns() - start_ns) / 1_000_000

        if error is not None:
            err_result = ToolCallResult(
                context=ctx,
                result="",
                duration_ms=duration_ms,
                error=error,
            )
            await post_chain.run_post_tool(err_result)
            raise error

        tool_result = ToolCallResult(
            context=ctx,
            result=result_str,
            duration_ms=duration_ms,
        )
        return await post_chain.run_post_tool(tool_result)


# ---------------------------------------------------------------------------
# Built-in hooks
# ---------------------------------------------------------------------------

# Cost-per-token estimates (USD) used by LLMCostLoggerHook.
# These are rough approximations; real cost depends on the deployed model.
_COST_PER_1K_TOKENS: dict[str, float] = {
    "gpt-4o": 0.005,
    "gpt-4": 0.03,
    "gpt-3.5-turbo": 0.002,
    "claude-3-opus": 0.015,
    "claude-3-sonnet": 0.003,
    "claude-3-haiku": 0.00025,
    "default": 0.002,
}

_LARGE_RESULT_THRESHOLD = 10_000  # characters


def _estimate_cost(model: str, total_tokens: int) -> float:
    """Return rough USD cost estimate for *total_tokens* on *model*."""
    rate = _COST_PER_1K_TOKENS.get(model, _COST_PER_1K_TOKENS["default"])
    return rate * total_tokens / 1000


async def llm_cost_logger_hook(result: LLMCallResult) -> LLMCallResult:
    """Built-in post_llm hook: logs token usage and estimated cost."""
    usage = result.response.usage
    cost = _estimate_cost(result.response.model, usage.total_tokens)
    logger.info(
        "LLM [%s] tokens=%d cost=$%.4f duration_ms=%.1f",
        result.context.run_id,
        usage.total_tokens,
        cost,
        result.duration_ms,
    )
    return result


async def tool_result_size_hook(result: ToolCallResult) -> ToolCallResult:
    """Built-in post_tool hook: logs tool result character count."""
    size = len(result.result)
    if size > _LARGE_RESULT_THRESHOLD:
        logger.warning(
            "Tool [%s] result_size=%d chars (exceeds %d threshold)",
            result.context.tool_name,
            size,
            _LARGE_RESULT_THRESHOLD,
        )
    else:
        logger.info(
            "Tool [%s] result_size=%d chars",
            result.context.tool_name,
            size,
        )
    return result
