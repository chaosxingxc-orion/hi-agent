"""Posture-matrix tests for config module callsites (Rule 11).

Covers:
  hi_agent/config/posture_guards.py      — require_tenant, require_spine
  hi_agent/config/json_config_loader.py  — _resolve_provider_api_key
  hi_agent/config/runtime_config_loader.py — get_posture

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to callsite function names.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# posture_guards.require_tenant
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_require_tenant(monkeypatch, posture_name, empty_raises):
    """Posture-matrix test for require_tenant.

    dev: empty tenant_id returns "" (permissive).
    research/prod: empty tenant_id raises ValueError.
    Non-empty always passes.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.config.posture_guards import require_tenant

    p = Posture(posture_name)
    result = require_tenant("t-valid", where="test", posture=p)
    assert result == "t-valid"

    if empty_raises:
        with pytest.raises(ValueError, match="empty tenant_id"):
            require_tenant("", where="test", posture=p)
    else:
        assert require_tenant("", where="test", posture=p) == ""


# ---------------------------------------------------------------------------
# posture_guards.require_spine
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,empty_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_require_spine(monkeypatch, posture_name, empty_raises):
    """Posture-matrix test for require_spine.

    dev: empty pair allowed.
    research/prod: empty tenant or project raises ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.config.posture_guards import require_spine

    p = Posture(posture_name)
    tid, pid = require_spine(tenant_id="t1", project_id="p1", where="test", posture=p)
    assert tid == "t1"
    assert pid == "p1"

    if empty_raises:
        with pytest.raises(ValueError, match="empty tenant_id"):
            require_spine(tenant_id="", project_id="p1", where="test", posture=p)
    else:
        tid, pid = require_spine(tenant_id="", project_id="", where="test", posture=p)
        assert tid == ""
        assert pid == ""


# ---------------------------------------------------------------------------
# json_config_loader._resolve_provider_api_key
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,missing_raises", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__resolve_provider_api_key(monkeypatch, posture_name, missing_raises):
    """Posture-matrix test for _resolve_provider_api_key.

    dev: missing api_key returns "" with warning.
    research/prod: missing api_key raises ValueError.
    Present key always returned.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.config.json_config_loader import _resolve_provider_api_key

    result, _ = _resolve_provider_api_key("openai", {"api_key": "sk-abc"})
    assert result == "sk-abc"

    if missing_raises:
        with pytest.raises(ValueError, match="api_key required"):
            _resolve_provider_api_key("openai", {"api_key": ""})
    else:
        result, _ = _resolve_provider_api_key("openai", {"api_key": ""})
        assert result == ""


# ---------------------------------------------------------------------------
# runtime_config_loader.get_posture
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_get_posture(monkeypatch, posture_name):
    """get_posture() reflects HI_AGENT_POSTURE in all three postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.config.runtime_config_loader import get_posture
    assert get_posture() == Posture(posture_name)
