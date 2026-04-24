"""Integration tests: invoker raises CapabilityUnavailableError for unavailable caps."""

from unittest.mock import MagicMock

import pytest
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor
from hi_agent.capability.invoker import CapabilityInvoker, CapabilityUnavailableError
from hi_agent.capability.registry import CapabilityRegistry


def test_invoker_raises_for_unavailable_capability(monkeypatch):
    """Direct invoke of unavailable capability raises CapabilityUnavailableError.

    Boundary mocks:
    - ``spec`` (MagicMock): a CapabilitySpec registration entry — a data object, not the SUT.
    - ``breaker`` (MagicMock): circuit-breaker adapter — external seam, not the SUT.
    The SUT is CapabilityInvoker + real CapabilityRegistry.
    """
    monkeypatch.delenv("FAKE_KEY_W4003_INVOKER", raising=False)

    desc = CapabilityDescriptor(
        name="gated_cap",
        required_env={"FAKE_KEY_W4003_INVOKER": "test key"},
    )
    # Boundary mock: spec is a registration data-object stub, not the invoker under test.
    spec = MagicMock()
    spec.name = "gated_cap"
    spec.descriptor = desc
    spec.handler = MagicMock(return_value={"success": True})

    registry = CapabilityRegistry()
    registry._capabilities["gated_cap"] = spec

    # Boundary mock: circuit-breaker is an external seam; allow=True so it doesn't block.
    breaker = MagicMock()
    breaker.allow.return_value = True

    invoker = CapabilityInvoker(registry=registry, breaker=breaker, allow_unguarded=True)

    with pytest.raises(CapabilityUnavailableError) as exc_info:
        invoker.invoke("gated_cap", {})

    assert "gated_cap" in str(exc_info.value)
    assert "FAKE_KEY_W4003_INVOKER" in str(exc_info.value)


def test_invoker_allows_available_capability(monkeypatch):
    """Invoker proceeds normally for available capabilities.

    Boundary mocks:
    - ``spec`` (MagicMock): capability registration data-object, not the SUT.
    - ``breaker`` (MagicMock): circuit-breaker external seam.
    SUT: CapabilityInvoker + real CapabilityRegistry.
    """
    monkeypatch.setenv("FAKE_KEY_W4003_INVOKER", "sk-test")

    desc = CapabilityDescriptor(
        name="gated_cap",
        required_env={"FAKE_KEY_W4003_INVOKER": "test key"},
    )
    # Boundary mock: spec is a registration data-object stub, not the invoker under test.
    spec = MagicMock()
    spec.name = "gated_cap"
    spec.descriptor = desc
    spec.handler = MagicMock(return_value={"success": True, "output": "ok"})

    registry = CapabilityRegistry()
    registry._capabilities["gated_cap"] = spec

    # Boundary mock: circuit-breaker external seam; allow=True passes through.
    breaker = MagicMock()
    breaker.allow.return_value = True

    invoker = CapabilityInvoker(registry=registry, breaker=breaker, allow_unguarded=True)
    result = invoker.invoke("gated_cap", {})
    assert result["success"] is True


def test_invoker_skips_probe_when_registry_lacks_method():
    """If registry has no probe_availability, invoker proceeds normally (backward compat).

    Boundary mocks:
    - ``spec`` (MagicMock): capability registration data-object stub.
    - ``registry`` (MagicMock): used here to simulate an older registry that lacks
      ``probe_availability``; the SUT (CapabilityInvoker) must handle this gracefully.
      This is the minimal seam needed to test a backward-compat code path without
      the real CapabilityRegistry (which always has probe_availability).
    - ``breaker`` (MagicMock): circuit-breaker external seam.
    """
    # Boundary mock: data-object stub for capability spec.
    spec = MagicMock()
    spec.name = "cap"
    spec.handler = MagicMock(return_value={"success": True})

    # Boundary mock: simulates an older registry missing probe_availability.
    # A real CapabilityRegistry always has this method, so a MagicMock is the
    # only way to exercise the backward-compat branch without monkey-patching.
    registry = MagicMock()
    registry.get.return_value = spec
    del registry.probe_availability  # ensure hasattr returns False

    # Boundary mock: circuit-breaker external seam.
    breaker = MagicMock()
    breaker.allow.return_value = True

    invoker = CapabilityInvoker(registry=registry, breaker=breaker, allow_unguarded=True)
    result = invoker.invoke("cap", {})
    assert result["success"] is True


def test_capability_unavailable_error_attributes():
    err = CapabilityUnavailableError("my_cap", "missing key")
    assert err.capability_name == "my_cap"
    assert err.reason == "missing key"
    assert "my_cap" in str(err)
