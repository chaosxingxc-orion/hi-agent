"""Tests for hi_agent.middleware.hooks — fine-grained execution hook system."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
from hi_agent.llm.protocol import LLMRequest, LLMResponse, TokenUsage
from hi_agent.middleware.hooks import (
    ExecutionHookManager,
    HookChain,
    HookEvent,
    HookRegistry,
    LLMCallContext,
    LLMCallResult,
    ToolCallContext,
    ToolCallResult,
    llm_cost_logger_hook,
    tool_result_size_hook,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_request() -> LLMRequest:
    return LLMRequest(messages=[{"role": "user", "content": "hello"}])


def _make_llm_response(total_tokens: int = 100) -> LLMResponse:
    return LLMResponse(
        content="answer",
        model="gpt-4o",
        usage=TokenUsage(prompt_tokens=50, completion_tokens=50, total_tokens=total_tokens),
    )


def _make_llm_ctx(run_id: str = "run-001", turn: int = 1) -> LLMCallContext:
    return LLMCallContext(
        run_id=run_id,
        stage_id="stage-1",
        turn_number=turn,
        request=_make_llm_request(),
    )


def _make_tool_ctx(tool_name: str = "search") -> ToolCallContext:
    return ToolCallContext(
        run_id="run-001",
        stage_id="stage-1",
        tool_name=tool_name,
        tool_input={"query": "test"},
        turn_number=1,
    )


# ---------------------------------------------------------------------------
# 1. HookRegistry: register and retrieve chain
# ---------------------------------------------------------------------------


def test_hook_registry_register_and_get() -> None:
    registry = HookRegistry()
    dummy_hook = AsyncMock(side_effect=lambda ctx: ctx)

    registry.register(HookEvent.PRE_LLM_CALL, dummy_hook, name="my_hook")
    chain = registry.get_chain(HookEvent.PRE_LLM_CALL)

    assert isinstance(chain, HookChain)
    assert len(chain) == 1


# ---------------------------------------------------------------------------
# 2. HookChain: pre_llm hooks run in order with output chaining
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_chain_runs_pre_llm_hooks_in_order() -> None:
    call_log: list[str] = []

    async def hook_a(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("a")
        ctx.metadata["a"] = True
        return ctx

    async def hook_b(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("b")
        # Depends on hook_a having run first (metadata key "a" must exist)
        assert ctx.metadata.get("a") is True
        ctx.metadata["b"] = True
        return ctx

    chain = HookChain(name="test", event=HookEvent.PRE_LLM_CALL)
    chain.register(hook_a)
    chain.register(hook_b)

    ctx = _make_llm_ctx()
    result_ctx = await chain.run_pre_llm(ctx)

    assert call_log == ["a", "b"]
    assert result_ctx.metadata["a"] is True
    assert result_ctx.metadata["b"] is True


# ---------------------------------------------------------------------------
# 3. HookChain: a failing hook is skipped, chain continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_chain_isolates_failing_hook() -> None:
    call_log: list[str] = []

    async def good_hook_1(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("good_1")
        return ctx

    async def bad_hook(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("bad")
        raise RuntimeError("intentional failure")

    async def good_hook_2(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("good_2")
        return ctx

    chain = HookChain(name="test", event=HookEvent.PRE_LLM_CALL)
    chain.register(good_hook_1)
    chain.register(bad_hook)
    chain.register(good_hook_2)

    ctx = _make_llm_ctx()
    result_ctx = await chain.run_pre_llm(ctx)

    # bad_hook raised but the chain recovered and ran good_hook_2
    assert call_log == ["good_1", "bad", "good_2"]
    # The returned context is still valid
    assert result_ctx.run_id == "run-001"


# ---------------------------------------------------------------------------
# 4. HookChain: supports both sync and async hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_chain_supports_sync_and_async_hooks() -> None:
    call_log: list[str] = []

    def sync_hook(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("sync")
        ctx.metadata["sync"] = True
        return ctx

    async def async_hook(ctx: LLMCallContext) -> LLMCallContext:
        call_log.append("async")
        ctx.metadata["async"] = True
        return ctx

    chain = HookChain(name="test", event=HookEvent.PRE_LLM_CALL)
    chain.register(sync_hook)
    chain.register(async_hook)

    ctx = _make_llm_ctx()
    result_ctx = await chain.run_pre_llm(ctx)

    assert call_log == ["sync", "async"]
    assert result_ctx.metadata["sync"] is True
    assert result_ctx.metadata["async"] is True


# ---------------------------------------------------------------------------
# 5. ExecutionHookManager: wrap_llm_call (pre → call → post)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_hook_manager_wrap_llm_call() -> None:
    order: list[str] = []

    async def pre_hook(ctx: LLMCallContext) -> LLMCallContext:
        order.append("pre")
        return ctx

    async def post_hook(result: LLMCallResult) -> LLMCallResult:
        order.append("post")
        return result

    registry = HookRegistry()
    registry.register(HookEvent.PRE_LLM_CALL, pre_hook)
    registry.register(HookEvent.POST_LLM_CALL, post_hook)

    async def fake_llm(request: LLMRequest) -> LLMResponse:
        order.append("call")
        return _make_llm_response()

    manager = ExecutionHookManager(registry)
    ctx = _make_llm_ctx()
    result = await manager.wrap_llm_call(ctx, fake_llm)

    assert order == ["pre", "call", "post"]
    assert isinstance(result, LLMCallResult)
    assert result.response.content == "answer"
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# 6. ExecutionHookManager: wrap_tool_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_hook_manager_wrap_tool_call() -> None:
    order: list[str] = []

    async def pre_hook(ctx: ToolCallContext) -> ToolCallContext:
        order.append("pre")
        return ctx

    async def post_hook(result: ToolCallResult) -> ToolCallResult:
        order.append("post")
        return result

    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL, pre_hook)
    registry.register(HookEvent.POST_TOOL, post_hook)

    async def fake_tool(ctx: ToolCallContext) -> str:
        order.append("call")
        return "tool output"

    manager = ExecutionHookManager(registry)
    ctx = _make_tool_ctx()
    result = await manager.wrap_tool_call(ctx, fake_tool)

    assert order == ["pre", "call", "post"]
    assert isinstance(result, ToolCallResult)
    assert result.result == "tool output"
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# 7. wrap_llm_call: exception still runs post hooks, then re-raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_llm_call_exception_still_runs_post() -> None:
    post_received: list[LLMCallResult] = []

    async def post_hook(result: LLMCallResult) -> LLMCallResult:
        post_received.append(result)
        return result

    registry = HookRegistry()
    registry.register(HookEvent.POST_LLM_CALL, post_hook)

    async def failing_llm(request: LLMRequest) -> LLMResponse:
        raise ValueError("LLM unavailable")

    manager = ExecutionHookManager(registry)
    ctx = _make_llm_ctx()

    with pytest.raises(ValueError, match="LLM unavailable"):
        await manager.wrap_llm_call(ctx, failing_llm)

    # post hook must have been called even though the LLM call failed
    assert len(post_received) == 1
    assert post_received[0].error is not None
    assert isinstance(post_received[0].error, ValueError)


# ---------------------------------------------------------------------------
# 8. Built-in: llm_cost_logger_hook logs token usage and cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_cost_logger_hook_logs(caplog: pytest.LogCaptureFixture) -> None:
    ctx = _make_llm_ctx(run_id="run-XYZ")
    response = _make_llm_response(total_tokens=200)
    result = LLMCallResult(context=ctx, response=response, duration_ms=42.0)

    with caplog.at_level(logging.INFO, logger="hi_agent.middleware.hooks"):
        returned = await llm_cost_logger_hook(result)

    assert returned is result  # pass-through
    # Verify log message contains run_id and token count
    log_text = " ".join(caplog.messages)
    assert "run-XYZ" in log_text
    assert "200" in log_text


# ---------------------------------------------------------------------------
# 9. Built-in: tool_result_size_hook warns on large results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_result_size_hook_warns_large_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = _make_tool_ctx(tool_name="big_query")
    large_output = "x" * 15_000  # exceeds 10_000 threshold
    result = ToolCallResult(context=ctx, result=large_output, duration_ms=5.0)

    with caplog.at_level(logging.WARNING, logger="hi_agent.middleware.hooks"):
        returned = await tool_result_size_hook(result)

    assert returned is result
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("big_query" in m for m in warning_messages)
    assert any("15000" in m for m in warning_messages)


@pytest.mark.asyncio
async def test_tool_result_size_hook_info_small_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = _make_tool_ctx(tool_name="small_query")
    small_output = "short result"
    result = ToolCallResult(context=ctx, result=small_output, duration_ms=1.0)

    with caplog.at_level(logging.INFO, logger="hi_agent.middleware.hooks"):
        returned = await tool_result_size_hook(result)

    assert returned is result
    # Should have an INFO log, NOT a WARNING
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warning_messages) == 0
    info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("small_query" in m for m in info_messages)


# ---------------------------------------------------------------------------
# 10. HookRegistry.clear
# ---------------------------------------------------------------------------


def test_hook_registry_clear() -> None:
    registry = HookRegistry()

    async def some_hook(ctx: LLMCallContext) -> LLMCallContext:
        return ctx

    registry.register(HookEvent.PRE_LLM_CALL, some_hook)
    registry.register(HookEvent.POST_LLM_CALL, some_hook)
    assert len(registry.get_chain(HookEvent.PRE_LLM_CALL)) == 1
    assert len(registry.get_chain(HookEvent.POST_LLM_CALL)) == 1

    # Clear only one event
    registry.clear(HookEvent.PRE_LLM_CALL)
    assert len(registry.get_chain(HookEvent.PRE_LLM_CALL)) == 0
    assert len(registry.get_chain(HookEvent.POST_LLM_CALL)) == 1  # untouched

    # Clear all
    registry.clear()
    assert len(registry.get_chain(HookEvent.POST_LLM_CALL)) == 0
    assert len(registry.get_chain(HookEvent.PRE_TOOL)) == 0
    assert len(registry.get_chain(HookEvent.POST_TOOL)) == 0
