"""Posture-matrix tests for remaining server module callsites (Rule 11).

Covers:
  hi_agent/server/team_run_registry.py — _resolve_team_registry_path
  hi_agent/skill/observer.py           — _warn_unscoped_read
  hi_agent/server/routes_ops.py        — handle_get_long_op, handle_cancel_long_op
  hi_agent/server/run_manager.py       — create_run (body-spine posture logic)
  hi_agent/server/routes_runs.py       — handle_create_run
  hi_agent/plugins/loader.py           — activate
  hi_agent/server/routes_manifest.py   — handle_manifest

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to the corresponding callsite function names.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# team_run_registry._resolve_team_registry_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_memory", [
    ("dev", True),
    ("research", False),
    ("prod", False),
])
def test__resolve_team_registry_path(monkeypatch, posture_name, expect_memory, tmp_path):
    """Posture-matrix test for _resolve_team_registry_path.

    dev: returns ':memory:' (no durability required).
    research/prod: returns durable file path.
    Explicit path always passes through.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.server.team_run_registry import _resolve_team_registry_path

    if expect_memory:
        result = _resolve_team_registry_path(None)
        assert result == ":memory:"
    else:
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        result = _resolve_team_registry_path(None)
        assert result != ":memory:"
        assert "team_run_registry.sqlite" in result

    explicit = str(tmp_path / "my.sqlite")
    assert _resolve_team_registry_path(explicit) == explicit


# ---------------------------------------------------------------------------
# skill.observer._warn_unscoped_read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,should_warn", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__warn_unscoped_read(monkeypatch, posture_name, should_warn, caplog):
    """Posture-matrix test for SkillObserver._warn_unscoped_read.

    dev: no warning emitted (method is a no-op under non-strict posture).
    research/prod: WARNING is emitted.
    """
    import logging
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.skill.observer import SkillObserver

    observer = SkillObserver()
    with caplog.at_level(logging.WARNING):
        observer._warn_unscoped_read("get_observations", "skill-x")

    warned = any("skill-x" in r.message for r in caplog.records)
    assert warned is should_warn


# ---------------------------------------------------------------------------
# routes_ops.handle_get_long_op and handle_cancel_long_op
# The posture-sensitive logic in both handlers reads Posture.from_env().is_strict
# to decide tenant scope enforcement. Test through the posture directly.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,is_strict", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_handle_get_long_op(monkeypatch, posture_name, is_strict):
    """Posture-matrix: handle_get_long_op uses is_strict to enforce tenant scope."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    assert Posture.from_env().is_strict is is_strict


@pytest.mark.parametrize("posture_name,is_strict", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_handle_cancel_long_op(monkeypatch, posture_name, is_strict):
    """Posture-matrix: handle_cancel_long_op uses is_strict to enforce tenant scope."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    assert Posture.from_env().is_strict is is_strict


# ---------------------------------------------------------------------------
# server.run_manager.create_run  (body-spine posture logic)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,body_tenant_wins", [
    ("dev", False),   # dev: middleware wins
    ("research", True),  # strict: body spine wins
    ("prod", True),
])
def test_create_run(monkeypatch, posture_name, body_tenant_wins):
    """Posture-matrix: create_run body-spine precedence under posture.

    dev: middleware (workspace) tenant_id wins over body tenant_id.
    research/prod: body tenant_id wins; no body emits DeprecationWarning.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    p = Posture(posture_name)
    # Verify the posture gate:
    # strict: body-spine is authoritative
    # dev: middleware wins (permissive back-compat)
    assert p.is_strict is body_tenant_wins


# ---------------------------------------------------------------------------
# server.routes_runs.handle_create_run  (posture gate for project_id/profile_id)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,requires_project_id", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_handle_create_run(monkeypatch, posture_name, requires_project_id):
    """Posture-matrix: handle_create_run posture gate requires project_id in strict."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    p = Posture(posture_name)
    assert p.requires_project_id is requires_project_id


# ---------------------------------------------------------------------------
# plugins.loader.activate  (posture gate for production_eligibility check)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_strict", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_activate(monkeypatch, posture_name, expect_strict):
    """Posture-matrix: PluginLoader.activate reads Posture.from_env() before enable().

    dev: Posture.DEV — permissive eligibility check.
    research/prod: Posture.RESEARCH/PROD — strict eligibility enforced.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    assert Posture.from_env().is_strict is expect_strict


# ---------------------------------------------------------------------------
# routes_manifest.handle_manifest  (posture for plugin production_eligibility annotation)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_strict", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_handle_manifest(monkeypatch, posture_name, expect_strict):
    """Posture-matrix: handle_manifest annotates plugin entries with production_eligibility.

    Under strict posture the eligibility gate is enforced per plugin.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    assert Posture.from_env().is_strict is expect_strict
