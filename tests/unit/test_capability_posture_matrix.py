"""Unit tests for the per-capability posture matrix wiring (W24 Track D / A-03).

Covers:
- ``CapabilityDescriptor.available_in_{dev,research,prod}`` fields exist
  (W22-A9 baseline) and default to ``True`` apart from registered exceptions.
- ``CapabilityRegistry.to_extension_manifest_dict()`` reads each descriptor's
  posture-matrix fields rather than emitting a hardcoded
  ``{dev:True, research:True, prod:True}`` constant — the regression test
  for the RIA audit finding at
  ``hi-agent-architecture-improvement-requirements-2026-04-29.md:129-153``.
- ``CapabilityRegistry.probe_availability_with_posture()`` returns ``True``
  when the descriptor permits the posture and raises
  ``CapabilityNotAvailableError`` when it does not.
- The structured 400 envelope returned by
  ``CapabilityNotAvailableError.to_envelope()`` matches the
  ``error_response`` shape consumed by ``hi_agent/server/error_categories.py``.
- Built-in ``shell_exec`` carries ``available_in_prod=False`` and the registry
  refuses to permit it under prod posture.
- The sync and async capability invokers consult the posture gate before
  dispatching, raising ``CapabilityNotAvailableError`` when the active posture
  forbids the capability.
"""

from __future__ import annotations

import pytest
from hi_agent.capability.invoker import CapabilityInvoker
from hi_agent.capability.registry import (
    CapabilityDescriptor,
    CapabilityNotAvailableError,
    CapabilityRegistry,
    CapabilitySpec,
)


def _make_registry() -> CapabilityRegistry:
    return CapabilityRegistry()


# ---------------------------------------------------------------------------
# Descriptor field surface
# ---------------------------------------------------------------------------


def test_descriptor_has_posture_fields():
    desc = CapabilityDescriptor(name="test_cap")
    assert hasattr(desc, "available_in_dev")
    assert hasattr(desc, "available_in_research")
    assert hasattr(desc, "available_in_prod")


def test_default_posture_all_true():
    desc = CapabilityDescriptor(name="test_cap")
    assert desc.available_in_dev is True
    assert desc.available_in_research is True
    assert desc.available_in_prod is True


# ---------------------------------------------------------------------------
# shell_exec: prod-blocked
# ---------------------------------------------------------------------------


def test_shell_exec_descriptor_prod_blocked():
    """Built-in ``shell_exec`` MUST default to ``available_in_prod=False``."""
    from hi_agent.capability.tools.builtin import get_builtin_capabilities

    caps = {spec.name: spec for spec in get_builtin_capabilities()}
    assert "shell_exec" in caps, "shell_exec must be in builtin capabilities list"
    desc = caps["shell_exec"].descriptor
    assert desc is not None
    assert desc.available_in_prod is False
    # dev and research remain permitted for legitimate developer / research use
    assert desc.available_in_dev is True
    assert desc.available_in_research is True


def test_shell_exec_blocked_under_prod_posture():
    """Posture gate denies shell_exec under prod and grants it under dev."""
    from hi_agent.capability.tools.builtin import get_builtin_capabilities

    registry = _make_registry()
    for spec in get_builtin_capabilities():
        if spec.name == "shell_exec":
            registry.register(spec)
            break
    assert "shell_exec" in registry.list_names()

    # prod: must raise
    with pytest.raises(CapabilityNotAvailableError) as exc_info:
        registry.probe_availability_with_posture("shell_exec", posture="prod")
    err = exc_info.value
    assert err.capability_name == "shell_exec"
    assert err.posture == "prod"

    # dev: must return True (no raise)
    assert registry.probe_availability_with_posture("shell_exec", posture="dev") is True

    # research: must return True (shell is permitted for research workflows)
    assert (
        registry.probe_availability_with_posture("shell_exec", posture="research")
        is True
    )


# ---------------------------------------------------------------------------
# Per-capability matrix variations
# ---------------------------------------------------------------------------


def test_dev_only_capability_blocked_under_research_and_prod():
    """A dev-only capability is denied under research and prod postures."""
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="dev_only_cap",
        available_in_dev=True,
        available_in_research=False,
        available_in_prod=False,
    )
    registry.register(
        CapabilitySpec(name="dev_only_cap", handler=lambda _: {}, descriptor=desc)
    )

    assert (
        registry.probe_availability_with_posture("dev_only_cap", posture="dev") is True
    )
    with pytest.raises(CapabilityNotAvailableError):
        registry.probe_availability_with_posture("dev_only_cap", posture="research")
    with pytest.raises(CapabilityNotAvailableError):
        registry.probe_availability_with_posture("dev_only_cap", posture="prod")


def test_research_only_capability_blocked_under_prod():
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="research_cap",
        available_in_dev=True,
        available_in_research=True,
        available_in_prod=False,
    )
    registry.register(
        CapabilitySpec(name="research_cap", handler=lambda _: {}, descriptor=desc)
    )

    assert (
        registry.probe_availability_with_posture("research_cap", posture="dev") is True
    )
    assert (
        registry.probe_availability_with_posture("research_cap", posture="research")
        is True
    )
    with pytest.raises(CapabilityNotAvailableError):
        registry.probe_availability_with_posture("research_cap", posture="prod")


def test_unregistered_capability_raises():
    registry = _make_registry()
    with pytest.raises(CapabilityNotAvailableError) as exc_info:
        registry.probe_availability_with_posture("ghost_cap", posture="prod")
    assert exc_info.value.capability_name == "ghost_cap"
    assert exc_info.value.posture == "prod"


# ---------------------------------------------------------------------------
# to_extension_manifest_dict — the regression test for the RIA audit finding
# ---------------------------------------------------------------------------


def test_manifest_dict_reads_descriptor_fields_not_hardcoded():
    """Per-descriptor posture matrix MUST flow through to manifest dict.

    Regression test for the RIA audit at
    ``hi-agent-architecture-improvement-requirements-2026-04-29.md:129-153``:
    historically ``to_extension_manifest_dict`` returned a hardcoded
    ``{"dev": True, "research": True, "prod": True}`` constant for every
    capability, hiding the per-capability matrix.  The fix makes it read
    each descriptor's three fields.
    """
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="restricted_cap",
        available_in_dev=True,
        available_in_research=True,
        available_in_prod=False,
    )
    registry.register(
        CapabilitySpec(name="restricted_cap", handler=lambda _: {}, descriptor=desc)
    )

    manifest = registry.to_extension_manifest_dict("restricted_cap")
    posture = manifest["posture_support"]
    assert posture["dev"] is True
    assert posture["research"] is True
    assert posture["prod"] is False  # would be True under the hardcoded bug


def test_manifest_dict_dev_only_capability_flows_through():
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="dev_only",
        available_in_dev=True,
        available_in_research=False,
        available_in_prod=False,
    )
    registry.register(
        CapabilitySpec(name="dev_only", handler=lambda _: {}, descriptor=desc)
    )
    manifest = registry.to_extension_manifest_dict("dev_only")
    assert manifest["posture_support"] == {
        "dev": True,
        "research": False,
        "prod": False,
    }


def test_manifest_dict_unregistered_returns_empty():
    registry = _make_registry()
    assert registry.to_extension_manifest_dict("never_registered") == {}


def test_manifest_dict_no_descriptor_defaults_all_true():
    """A spec without a descriptor falls back to all-True (legacy compat)."""
    registry = _make_registry()
    registry.register(
        CapabilitySpec(name="legacy_cap", handler=lambda _: {}, descriptor=None)
    )
    manifest = registry.to_extension_manifest_dict("legacy_cap")
    assert manifest["posture_support"] == {
        "dev": True,
        "research": True,
        "prod": True,
    }


# ---------------------------------------------------------------------------
# Error envelope structure
# ---------------------------------------------------------------------------


def test_capability_not_available_error_envelope_shape():
    err = CapabilityNotAvailableError("shell_exec", "prod")
    envelope = err.to_envelope()
    assert envelope["error_category"] == "invalid_request"
    assert "shell_exec" in envelope["message"]
    assert "prod" in envelope["message"]
    assert envelope["retryable"] is False
    assert envelope.get("next_action")
    assert envelope["capability_name"] == "shell_exec"
    assert envelope["posture"] == "prod"


def test_capability_not_available_error_attributes():
    err = CapabilityNotAvailableError("my_cap", "research", "custom reason")
    assert err.capability_name == "my_cap"
    assert err.posture == "research"
    assert err.reason == "custom reason"
    assert "custom reason" in str(err)


# ---------------------------------------------------------------------------
# Sync invoker dispatch path consults the posture gate
# ---------------------------------------------------------------------------


def test_sync_invoker_blocks_capability_under_disallowed_posture(monkeypatch):
    """CapabilityInvoker.invoke() must refuse posture-denied capabilities."""
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="prod_blocked",
        available_in_dev=True,
        available_in_research=True,
        available_in_prod=False,
    )
    called = {"count": 0}

    def _handler(_payload: dict) -> dict:
        called["count"] += 1
        return {"success": True}

    registry.register(
        CapabilitySpec(name="prod_blocked", handler=_handler, descriptor=desc)
    )

    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    invoker = CapabilityInvoker(registry=registry, allow_unguarded=True)
    with pytest.raises(CapabilityNotAvailableError) as exc_info:
        invoker.invoke("prod_blocked", {})
    assert exc_info.value.posture == "prod"
    assert called["count"] == 0  # handler MUST NOT have been called

    # Same invoker, dev posture: dispatch succeeds.
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    result = invoker.invoke("prod_blocked", {})
    assert result["success"] is True
    assert called["count"] == 1


def test_sync_invoker_permits_capability_when_posture_allows(monkeypatch):
    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="always_ok",
        available_in_dev=True,
        available_in_research=True,
        available_in_prod=True,
    )
    registry.register(
        CapabilitySpec(
            name="always_ok",
            handler=lambda _: {"success": True, "output": "ok"},
            descriptor=desc,
        )
    )
    invoker = CapabilityInvoker(registry=registry, allow_unguarded=True)
    for posture in ("dev", "research", "prod"):
        monkeypatch.setenv("HI_AGENT_POSTURE", posture)
        assert invoker.invoke("always_ok", {})["success"] is True


# ---------------------------------------------------------------------------
# Async invoker dispatch path consults the posture gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_invoker_blocks_capability_under_disallowed_posture(monkeypatch):
    from hi_agent.capability.async_invoker import AsyncCapabilityInvoker
    from hi_agent.capability.circuit_breaker import CircuitBreaker

    registry = _make_registry()
    desc = CapabilityDescriptor(
        name="prod_blocked_async",
        available_in_dev=True,
        available_in_research=True,
        available_in_prod=False,
    )
    called = {"count": 0}

    def _handler(_payload: dict) -> dict:
        called["count"] += 1
        return {"success": True}

    registry.register(
        CapabilitySpec(
            name="prod_blocked_async", handler=_handler, descriptor=desc
        )
    )

    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    invoker = AsyncCapabilityInvoker(registry=registry, breaker=CircuitBreaker())
    with pytest.raises(CapabilityNotAvailableError):
        await invoker.invoke("prod_blocked_async", {})
    assert called["count"] == 0
