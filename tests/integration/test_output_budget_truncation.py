"""Integration tests for output budget enforcement (HI-W10-004)."""

from hi_agent.capability.circuit_breaker import CircuitBreaker
from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec


def _registry_with_budget(cap_name: str, handler, budget_tokens: int) -> CapabilityRegistry:
    """Build a registry with a capability that has output_budget_tokens set."""
    registry = CapabilityRegistry()
    # CapabilitySpec is frozen; we subclass or use object.__setattr__ after construction
    spec = CapabilitySpec(name=cap_name, handler=handler)
    # Bypass frozen to attach budget — this mirrors how descriptor_factory attaches metadata
    object.__setattr__(spec, "output_budget_tokens", budget_tokens)  # type: ignore[misc]  expiry_wave: Wave 30
    registry.register(spec)
    return registry


def test_output_truncated_when_over_budget():
    """Response is trimmed and _output_truncated=True when over budget."""
    budget = 10
    large_output = "x" * (budget * 4 + 100)
    registry = _registry_with_budget("big_op", lambda _p: {"output": large_output}, budget)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)
    result = invoker.invoke("big_op", {})
    assert result.get("_output_truncated") is True
    assert len(result["output"]) <= budget * 4


def test_output_not_truncated_within_budget():
    """Short outputs are returned intact."""
    registry = _registry_with_budget("small_op", lambda _p: {"output": "short"}, 100)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)
    result = invoker.invoke("small_op", {})
    assert result.get("_output_truncated") is None
    assert result["output"] == "short"


def test_zero_budget_means_unlimited():
    """budget=0 (default) means no truncation."""
    big = "y" * 10_000
    registry = _registry_with_budget("unlimited_op", lambda _p: {"output": big}, 0)
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)
    result = invoker.invoke("unlimited_op", {})
    assert result.get("_output_truncated") is None
    assert len(result["output"]) == 10_000


def test_no_budget_attribute_means_unlimited():
    """Capability without output_budget_tokens is not truncated."""
    big = "z" * 5_000
    registry = CapabilityRegistry()
    registry.register(CapabilitySpec(name="plain_op", handler=lambda _p: {"result": big}))
    invoker = CapabilityInvoker(registry=registry, breaker=CircuitBreaker(), allow_unguarded=True)
    result = invoker.invoke("plain_op", {})
    assert result.get("_output_truncated") is None
