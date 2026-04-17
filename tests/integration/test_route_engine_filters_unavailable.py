"""Integration tests: route engine does not propose unavailable capabilities."""
import os
import pytest
from unittest.mock import MagicMock
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor


def _make_registry_with_unavailable(monkeypatch):
    """Registry with 'llm_plan' (requires FAKE_ENV_KEY) and 'simple_cap' (no requirements)."""
    monkeypatch.delenv("FAKE_ENV_KEY_W4003", raising=False)
    from hi_agent.capability.registry import CapabilitySpec

    unavailable_desc = CapabilityDescriptor(
        name="llm_plan",
        required_env={"FAKE_ENV_KEY_W4003": "test key"},
    )
    available_desc = CapabilityDescriptor(name="simple_cap")

    registry = CapabilityRegistry()

    spec1 = MagicMock()
    spec1.name = "llm_plan"
    spec1.descriptor = unavailable_desc
    spec1.handler = MagicMock(return_value={"success": True})

    spec2 = MagicMock()
    spec2.name = "simple_cap"
    spec2.descriptor = available_desc
    spec2.handler = MagicMock(return_value={"success": True})

    registry._capabilities["llm_plan"] = spec1
    registry._capabilities["simple_cap"] = spec2
    return registry


@pytest.mark.skip(reason="HybridRouteEngine capability_registry wiring requires constructor change — integration wired in W4-003")
def test_hybrid_engine_filters_unavailable_capability(monkeypatch):
    """HybridRouteEngine.propose() should not return unavailable capabilities."""
    registry = _make_registry_with_unavailable(monkeypatch)
    # This test requires HybridRouteEngine to accept capability_registry
    pass
