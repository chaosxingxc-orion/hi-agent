"""Tests for AsyncCapabilityInvoker, dead-end detection, and runner exception protection."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from hi_agent.capability.async_invoker import AsyncCapabilityInvoker
from hi_agent.capability.circuit_breaker import CircuitBreaker
from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry_with(name: str, handler) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(CapabilitySpec(name=name, handler=handler))
    return reg


def _make_executor(**overrides: Any) -> RunExecutor:
    defaults: dict[str, Any] = {
        "contract": TaskContract(
            task_id="t-async-001",
            goal="Test async invoker",
            task_family="quick_task",
        ),
        "kernel": MockKernel(),
        "route_engine": RuleRouteEngine(),
        "event_emitter": EventEmitter(),
        "raw_memory": RawMemoryStore(),
        "compressor": MemoryCompressor(),
        "acceptance_policy": AcceptancePolicy(),
        "cts_budget": CTSExplorationBudget(),
        "policy_versions": PolicyVersionSet(),
        "session": None,
    }
    defaults.update(overrides)
    return RunExecutor(**defaults)


# ======================================================================
# Part 1: AsyncCapabilityInvoker tests
# ======================================================================


@pytest.mark.asyncio
async def test_async_invoke_success():
    """Basic async invoke returns result."""

    async def handler(payload: dict) -> dict:
        return {"status": "ok", "echo": payload.get("msg")}

    reg = _registry_with("greet", handler)
    breaker = CircuitBreaker()
    invoker = AsyncCapabilityInvoker(registry=reg, breaker=breaker)

    result = await invoker.invoke("greet", {"msg": "hello"})
    assert result == {"status": "ok", "echo": "hello"}


@pytest.mark.asyncio
async def test_async_invoke_timeout():
    """Times out and raises TimeoutError."""

    async def slow_handler(payload: dict) -> dict:
        await asyncio.sleep(10)
        return {"done": True}

    reg = _registry_with("slow", slow_handler)
    breaker = CircuitBreaker()
    invoker = AsyncCapabilityInvoker(registry=reg, breaker=breaker, call_timeout_seconds=0.05)

    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await invoker.invoke("slow", {})


@pytest.mark.asyncio
async def test_async_invoke_retry_with_backoff():
    """Retries on failure then succeeds."""
    call_count = 0

    async def flaky_handler(payload: dict) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("transient error")
        return {"ok": True}

    reg = _registry_with("flaky", flaky_handler)
    breaker = CircuitBreaker(failure_threshold=10)
    invoker = AsyncCapabilityInvoker(
        registry=reg,
        breaker=breaker,
        max_retries=3,
        retry_exceptions=(ValueError,),
        base_delay=0.01,
        jitter=0.001,
    )

    result = await invoker.invoke("flaky", {})
    assert result == {"ok": True}
    assert call_count == 3


@pytest.mark.asyncio
async def test_async_invoke_circuit_open():
    """Raises RuntimeError when circuit open."""

    async def handler(payload: dict) -> dict:
        return {"ok": True}

    reg = _registry_with("guarded", handler)
    breaker = CircuitBreaker(failure_threshold=1)
    # Force the circuit open
    breaker.mark_failure("guarded")

    invoker = AsyncCapabilityInvoker(registry=reg, breaker=breaker)

    with pytest.raises(RuntimeError, match="circuit open"):
        await invoker.invoke("guarded", {})


@pytest.mark.asyncio
async def test_async_invoke_sync_handler():
    """Wraps sync handler correctly via asyncio.to_thread."""

    def sync_handler(payload: dict) -> dict:
        return {"sync": True, "val": payload.get("x", 0) + 1}

    reg = _registry_with("sync_cap", sync_handler)
    breaker = CircuitBreaker()
    invoker = AsyncCapabilityInvoker(registry=reg, breaker=breaker)

    result = await invoker.invoke("sync_cap", {"x": 41})
    assert result == {"sync": True, "val": 42}


# ======================================================================
# Part 2: Dead-end detection in runner
# ======================================================================


@pytest.mark.skip(  # expiry_wave: Wave 35  W31-D D-2': MagicMock-on-SUT rewrite deferred
    reason=(
        "H1-Track4 K-11: mocks executor._execute_action_with_retry, which is an "
        "internal method of the SUT (RunExecutor). Mocking an internal method makes "
        "this a unit test of the dead-end detection branch only, not an integration "
        "test. Rule 4 honesty: needs rewrite using a real capability registry that "
        "returns failure results, exercising the full code path without SUT mock."
    )
)
def test_dead_end_detection_in_runner():
    """When all nodes in a stage fail, execute() returns 'failed'."""
    executor = _make_executor()

    # Patch the route engine to produce one proposal that will fail
    failing_proposal = MagicMock()
    failing_proposal.rationale = "attempt"
    failing_proposal.branch_id = "b1"
    failing_proposal.action_kind = "test_action"
    failing_proposal.capability_name = "cap"
    failing_proposal.payload = {}

    executor.route_engine = MagicMock()
    executor.route_engine.propose = MagicMock(return_value=[failing_proposal])

    # Make the action execution always fail
    executor._execute_action_with_retry = MagicMock(
        return_value=(False, {"failure_code": "harness_denied"}, 0)
    )

    # Patch acceptance policy so it doesn't interfere
    executor.acceptance_policy = MagicMock()

    result = executor.execute()
    assert result == "failed"


# ======================================================================
# Part 3: Runner exception protection
# ======================================================================


def test_runner_exception_protection():
    """An exception in _execute_stage leads to 'failed', not a crash."""
    executor = _make_executor()

    # Make _execute_stage raise an unexpected error
    _ = executor._execute_stage

    def exploding_stage(stage_id: str):
        raise RuntimeError("unexpected kaboom")

    executor._execute_stage = exploding_stage  # type: ignore[assignment]  expiry_wave: permanent

    result = executor.execute()
    assert result == "failed"

    # Verify a RunError event was recorded
    events = executor.event_emitter.events
    run_error_events = [e for e in events if e.event_type == "RunError"]
    assert len(run_error_events) == 1
    assert "unexpected kaboom" in run_error_events[0].payload["error"]
