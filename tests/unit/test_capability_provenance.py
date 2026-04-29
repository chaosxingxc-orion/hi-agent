"""Unit tests for capability/action-level provenance (HI-W2-002)."""

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.usefixtures("fallback_explicit")

from hi_agent.capability.invoker import CapabilityInvoker


def _make_invoker(handler_return):
    registry = MagicMock()
    spec = MagicMock()
    spec.handler = MagicMock(return_value=handler_return)
    registry.get.return_value = spec
    breaker = MagicMock()
    breaker.allow.return_value = True
    # allow_unguarded=True: these unit tests verify provenance annotation behavior,
    # not governance; no policy is needed here.
    return CapabilityInvoker(registry=registry, breaker=breaker, allow_unguarded=True)


def test_invoke_attaches_provenance_to_result():
    invoker = _make_invoker({"success": True, "output": "ok"})
    result = invoker.invoke("test_cap", {})
    assert "_provenance" in result
    assert result["_provenance"]["capability_name"] == "test_cap"
    assert result["_provenance"]["mode"] == "sample"
    assert isinstance(result["_provenance"]["duration_ms"], int)


def test_invoke_mcp_result_gets_mcp_mode():
    invoker = _make_invoker({"success": True, "_mcp": True})
    result = invoker.invoke("mcp_cap", {})
    assert result["_provenance"]["mode"] == "mcp"


def test_invoke_does_not_override_existing_provenance():
    existing_prov = {"mode": "profile", "capability_name": "x", "duration_ms": 5}
    invoker = _make_invoker({"success": True, "_provenance": existing_prov})
    result = invoker.invoke("cap", {})
    assert result["_provenance"]["mode"] == "profile"


def test_heuristic_handler_result_has_provenance():
    from hi_agent.capability.defaults import make_llm_capability_handler

    # gateway=None triggers heuristic fallback in non-prod env
    handler = make_llm_capability_handler("plan", "You are a planner.", None)
    result = handler({"goal": "test", "stage_id": "s1"})
    assert "_provenance" in result
    assert result["_provenance"]["mode"] == "sample"
    assert result["_provenance"]["capability_name"] == "plan"


def test_invoke_external_result_gets_external_mode():
    invoker = _make_invoker({"success": True, "_external": True})
    result = invoker.invoke("ext_cap", {})
    assert result["_provenance"]["mode"] == "external"


def test_invoke_profile_result_gets_profile_mode():
    invoker = _make_invoker({"success": True, "_profile": True})
    result = invoker.invoke("profile_cap", {})
    assert result["_provenance"]["mode"] == "profile"


def test_invoke_does_not_mutate_original_handler_response():
    """Invoker must copy the response dict, not mutate the original."""
    original = {"success": True, "output": "x"}
    invoker = _make_invoker(original)
    invoker.invoke("cap", {})
    # Original dict must not have been mutated
    assert "_provenance" not in original


def test_invoke_non_dict_response_returned_unchanged():
    """Non-dict handler responses pass through without modification."""
    invoker = _make_invoker("plain string")
    result = invoker.invoke("cap", {})
    assert result == "plain string"
