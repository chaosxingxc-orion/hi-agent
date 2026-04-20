"""Test that HarnessExecutor is properly wired with capability_invoker."""

from __future__ import annotations

import os

import pytest

# Allow heuristic fallback so tests work without real LLM credentials.
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.harness.contracts import ActionSpec, EffectClass, SideEffectClass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_builder() -> SystemBuilder:
    config = TraceConfig()
    return SystemBuilder(config=config)


def _analyze_goal_spec(action_id: str = "act-wiring-1") -> ActionSpec:
    """ActionSpec that targets the 'analyze_goal' capability registered by defaults."""
    return ActionSpec(
        action_id=action_id,
        action_type="read",
        capability_name="analyze_goal",
        payload={"goal": "Test wiring", "stage_id": "stage-1", "context": ""},
        effect_class=EffectClass.READ_ONLY,
        side_effect_class=SideEffectClass.READ_ONLY,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_invoker_returns_real_invoker() -> None:
    """build_invoker() must return a real CapabilityInvoker (not None)."""
    from hi_agent.capability.invoker import CapabilityInvoker

    builder = _make_builder()
    invoker = builder.build_invoker()

    assert invoker is not None
    assert isinstance(invoker, CapabilityInvoker)


def test_build_invoker_has_default_capabilities() -> None:
    """The invoker built by build_invoker() must have the default TRACE capabilities."""
    builder = _make_builder()
    invoker = builder.build_invoker()

    # The registry should have at least the default capabilities registered.
    names = invoker.registry.list_names()
    assert len(names) > 0, "CapabilityRegistry must have at least one registered capability"
    assert "analyze_goal" in names


def test_build_harness_has_invoker() -> None:
    """HarnessExecutor built by SystemBuilder must have a real invoker, not None."""
    builder = _make_builder()
    harness = builder.build_harness()

    assert harness._invoker is not None, (
        "HarnessExecutor._invoker must not be None after build_harness()"
    )


def test_build_harness_accepts_explicit_invoker() -> None:
    """build_harness(capability_invoker=...) must wire the supplied invoker."""
    builder = _make_builder()
    invoker = builder.build_invoker()
    harness = builder.build_harness(capability_invoker=invoker)

    assert harness._invoker is invoker


def test_harness_dispatch_does_not_raise_runtime_error() -> None:
    """HarnessExecutor.execute() must not raise RuntimeError due to None invoker.

    This test dispatches a read-only action through the full harness pipeline.
    The action targets 'analyze_goal' which is registered by default.  In
    heuristic-fallback mode (HI_AGENT_ALLOW_HEURISTIC_FALLBACK=1) the handler
    returns a synthetic dict without calling the LLM.
    """
    builder = _make_builder()
    harness = builder.build_harness()

    spec = _analyze_goal_spec()
    try:
        result = harness.execute(spec)
    except RuntimeError as exc:
        pytest.fail(f"HarnessExecutor raised RuntimeError (invoker not wired): {exc}")

    # We expect either success or a graceful failure — never a wiring error.
    assert result is not None
    assert result.action_id == spec.action_id
