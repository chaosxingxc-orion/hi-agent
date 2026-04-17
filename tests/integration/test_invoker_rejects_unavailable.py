"""Integration tests: invoker raises CapabilityUnavailableError for unavailable caps."""
import pytest
from unittest.mock import MagicMock
from hi_agent.capability.invoker import CapabilityInvoker, CapabilityUnavailableError
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor


def test_invoker_raises_for_unavailable_capability(monkeypatch):
    """Direct invoke of unavailable capability raises CapabilityUnavailableError."""
    monkeypatch.delenv("FAKE_KEY_W4003_INVOKER", raising=False)

    desc = CapabilityDescriptor(
        name="gated_cap",
        required_env={"FAKE_KEY_W4003_INVOKER": "test key"},
    )
    spec = MagicMock()
    spec.name = "gated_cap"
    spec.descriptor = desc
    spec.handler = MagicMock(return_value={"success": True})

    registry = CapabilityRegistry()
    registry._capabilities["gated_cap"] = spec

    breaker = MagicMock()
    breaker.allow.return_value = True

    invoker = CapabilityInvoker(registry=registry, breaker=breaker)

    with pytest.raises(CapabilityUnavailableError) as exc_info:
        invoker.invoke("gated_cap", {})

    assert "gated_cap" in str(exc_info.value)
    assert "FAKE_KEY_W4003_INVOKER" in str(exc_info.value)


def test_invoker_allows_available_capability(monkeypatch):
    """Invoker proceeds normally for available capabilities."""
    monkeypatch.setenv("FAKE_KEY_W4003_INVOKER", "sk-test")

    desc = CapabilityDescriptor(
        name="gated_cap",
        required_env={"FAKE_KEY_W4003_INVOKER": "test key"},
    )
    spec = MagicMock()
    spec.name = "gated_cap"
    spec.descriptor = desc
    spec.handler = MagicMock(return_value={"success": True, "output": "ok"})

    registry = CapabilityRegistry()
    registry._capabilities["gated_cap"] = spec

    breaker = MagicMock()
    breaker.allow.return_value = True

    invoker = CapabilityInvoker(registry=registry, breaker=breaker)
    result = invoker.invoke("gated_cap", {})
    assert result["success"] is True


def test_invoker_skips_probe_when_registry_lacks_method():
    """If registry has no probe_availability, invoker proceeds normally (backward compat)."""
    spec = MagicMock()
    spec.name = "cap"
    spec.handler = MagicMock(return_value={"success": True})

    # Registry without probe_availability
    registry = MagicMock()
    registry.get.return_value = spec
    del registry.probe_availability  # ensure hasattr returns False

    breaker = MagicMock()
    breaker.allow.return_value = True

    invoker = CapabilityInvoker(registry=registry, breaker=breaker)
    result = invoker.invoke("cap", {})
    assert result["success"] is True


def test_capability_unavailable_error_attributes():
    err = CapabilityUnavailableError("my_cap", "missing key")
    assert err.capability_name == "my_cap"
    assert err.reason == "missing key"
    assert "my_cap" in str(err)
