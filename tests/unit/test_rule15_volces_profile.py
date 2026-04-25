"""Unit tests for the rule15_volces profile (DF-33).

Asserts the profile can be built, registered, and has the expected shape.
The LLM gateway is NOT invoked — live verification is Task E's job.
"""

from __future__ import annotations

from hi_agent.config.builder import SystemBuilder
from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.profiles.rule15_volces import (
    RULE15_PROBE_CAPABILITY,
    RULE15_PROBE_STAGE,
    build_rule15_volces_profile,
    register_rule15_probe_capability,
)


def test_build_rule15_volces_profile_shape() -> None:
    spec = build_rule15_volces_profile()
    assert isinstance(spec, ProfileSpec)
    assert spec.profile_id == "rule15_volces"
    assert RULE15_PROBE_CAPABILITY in spec.required_capabilities
    assert spec.stage_actions == {RULE15_PROBE_STAGE: RULE15_PROBE_CAPABILITY}
    assert spec.stage_graph_factory is not None


def test_rule15_volces_stage_graph_has_single_stage() -> None:
    spec = build_rule15_volces_profile()
    sg = spec.stage_graph_factory()
    assert RULE15_PROBE_STAGE in sg.transitions
    assert len(sg.transitions) == 1
    # No outgoing edges — single-stage profile.
    assert sg.transitions[RULE15_PROBE_STAGE] == set()


def test_rule15_volces_profile_registers_via_builder() -> None:
    builder = SystemBuilder()
    builder.register_profile(build_rule15_volces_profile())
    registry = builder.build_profile_registry()
    assert registry is not None
    spec = registry.get("rule15_volces")
    assert spec is not None
    assert spec.profile_id == "rule15_volces"
    assert RULE15_PROBE_CAPABILITY in spec.required_capabilities


def test_register_rule15_probe_capability_with_stub_gateway() -> None:
    """Register the probe capability with a None gateway (heuristic fallback allowed).

    Unit-level assertion only — the live-call path is covered by Task E.
    """
    import os

    os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

    from hi_agent.capability.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    register_rule15_probe_capability(registry, llm_gateway=None)

    assert RULE15_PROBE_CAPABILITY in registry.list_names()

    # Idempotent: second call is a no-op, does not raise.
    register_rule15_probe_capability(registry, llm_gateway=None)
    assert RULE15_PROBE_CAPABILITY in registry.list_names()


def test_rule15_probe_capability_handler_executes() -> None:
    """Invoke the registered handler to confirm it returns a well-formed dict."""
    import os

    os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

    from hi_agent.capability.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    register_rule15_probe_capability(registry, llm_gateway=None)
    spec = registry.get(RULE15_PROBE_CAPABILITY)
    assert spec is not None

    result = spec.handler({"stage_id": RULE15_PROBE_STAGE, "goal": "probe", "run_id": "test-run"})
    assert isinstance(result, dict)
    assert result.get("success") is True
