"""Tests for capability subsystem."""

import pytest
from hi_agent.capability import (
    CapabilityInvoker,
    CapabilityRegistry,
    CapabilitySpec,
    CircuitBreaker,
)


class _FakeClock:
    """Mutable clock used by cooldown-based tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_capability_invoker_success() -> None:
    """Invoker should return handler response on success."""
    registry = CapabilityRegistry()
    breaker = CircuitBreaker(failure_threshold=2)
    invoker = CapabilityInvoker(registry, breaker)

    registry.register(CapabilitySpec(name="echo", handler=lambda payload: {"echo": payload["x"]}))
    response = invoker.invoke("echo", {"x": 3})

    assert response == {"echo": 3}


def test_capability_breaker_opens_after_failures() -> None:
    """Breaker should open after repeated failures."""
    registry = CapabilityRegistry()
    breaker = CircuitBreaker(failure_threshold=2)
    invoker = CapabilityInvoker(registry, breaker)

    def fail(_payload: dict) -> dict:
        raise RuntimeError("boom")

    registry.register(CapabilitySpec(name="fail", handler=fail))

    with pytest.raises(RuntimeError):
        invoker.invoke("fail", {})
    with pytest.raises(RuntimeError):
        invoker.invoke("fail", {})
    with pytest.raises(RuntimeError, match="circuit open"):
        invoker.invoke("fail", {})


def test_capability_breaker_half_open_probe_success_recovers() -> None:
    """Breaker should recover after cooldown when probe call succeeds."""
    registry = CapabilityRegistry()
    clock = _FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, clock=clock)
    invoker = CapabilityInvoker(registry, breaker)

    attempts = {"count": 0}

    def flaky(_payload: dict) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom once")
        return {"ok": True}

    registry.register(CapabilitySpec(name="flaky", handler=flaky))

    with pytest.raises(RuntimeError):
        invoker.invoke("flaky", {})
    with pytest.raises(RuntimeError, match="circuit open"):
        invoker.invoke("flaky", {})

    clock.advance(5.0)
    assert invoker.invoke("flaky", {}) == {"ok": True}
    assert invoker.invoke("flaky", {}) == {"ok": True}
