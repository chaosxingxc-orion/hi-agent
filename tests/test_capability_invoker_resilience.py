"""Resilience tests for capability invoker retries and timeouts."""

import pytest
from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CapabilitySpec,
    CircuitBreaker,
)


def test_invoker_retries_and_eventually_succeeds() -> None:
    """Invoker retries retryable errors and returns successful response."""
    registry = CapabilityRegistry()
    breaker = CircuitBreaker(failure_threshold=10)

    attempts = {"count": 0}

    def flaky(_payload: dict) -> dict:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    registry.register(CapabilitySpec(name="flaky", handler=flaky))
    invoker = CapabilityInvoker(
        registry,
        breaker,
        max_retries=2,
        retry_exceptions=(RuntimeError,),
    )

    response = invoker.invoke("flaky", {})

    assert response == {"ok": True}
    assert attempts["count"] == 3


def test_invoker_retry_exhausted_raises_last_exception() -> None:
    """Invoker raises after max retries are exhausted."""
    registry = CapabilityRegistry()
    breaker = CircuitBreaker(failure_threshold=10)

    attempts = {"count": 0}

    def always_fails(_payload: dict) -> dict:
        attempts["count"] += 1
        raise RuntimeError(f"boom-{attempts['count']}")

    registry.register(CapabilitySpec(name="always_fails", handler=always_fails))
    invoker = CapabilityInvoker(
        registry,
        breaker,
        max_retries=2,
        retry_exceptions=(RuntimeError,),
    )

    with pytest.raises(RuntimeError, match="boom-3"):
        invoker.invoke("always_fails", {})

    assert attempts["count"] == 3


def test_invoker_non_retry_exception_fails_fast() -> None:
    """Invoker should not retry non-retryable exceptions."""
    registry = CapabilityRegistry()
    breaker = CircuitBreaker(failure_threshold=10)

    attempts = {"count": 0}

    def fails_with_value_error(_payload: dict) -> dict:
        attempts["count"] += 1
        raise ValueError("fatal")

    registry.register(CapabilitySpec(name="value_error", handler=fails_with_value_error))
    invoker = CapabilityInvoker(
        registry,
        breaker,
        max_retries=5,
        retry_exceptions=(RuntimeError,),
    )

    with pytest.raises(ValueError, match="fatal"):
        invoker.invoke("value_error", {})

    assert attempts["count"] == 1


def test_invoker_timeout_classified_as_retryable() -> None:
    """Timeout errors from timeout wrapper should be retried when configured."""
    registry = CapabilityRegistry()
    breaker = CircuitBreaker(failure_threshold=10)

    handler_attempts = {"count": 0}

    def echo(payload: dict) -> dict:
        handler_attempts["count"] += 1
        return {"echo": payload["x"]}

    timeout_calls: list[float] = []

    def fake_timeout_call(handler, payload: dict, timeout_seconds: float):
        timeout_calls.append(timeout_seconds)
        if len(timeout_calls) == 1:
            raise TimeoutError("timed out")
        return handler(payload)

    registry.register(CapabilitySpec(name="echo", handler=echo))
    invoker = CapabilityInvoker(
        registry,
        breaker,
        max_retries=1,
        retry_exceptions=(TimeoutError,),
        call_timeout_seconds=0.25,
        timeout_call=fake_timeout_call,
    )

    response = invoker.invoke("echo", {"x": 7})

    assert response == {"echo": 7}
    assert handler_attempts["count"] == 1
    assert timeout_calls == [0.25, 0.25]
