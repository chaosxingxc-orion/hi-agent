"""Posture-matrix tests for artifact module callsites (Rule 11).

Covers:
  hi_agent/artifacts/ledger.py   — _resolve_ledger_path, _allow_legacy, _tenant_visible
  hi_agent/artifacts/registry.py — ArtifactRegistry.__init__

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to callsite function names.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# ledger._resolve_ledger_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_none", [
    ("dev", True),
    ("research", False),
    ("prod", False),
])
def test__resolve_ledger_path(monkeypatch, posture_name, expect_none, tmp_path):
    """Posture-matrix test for _resolve_ledger_path.

    dev: None returns None (in-memory).
    research/prod: None without HI_AGENT_DATA_DIR raises; with it returns path.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.artifacts.ledger import _resolve_ledger_path

    if expect_none:
        result = _resolve_ledger_path(None)
        assert result is None
    else:
        monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)
        with pytest.raises(ValueError, match="HI_AGENT_DATA_DIR"):
            _resolve_ledger_path(None)
        # With data dir: returns path
        monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
        result = _resolve_ledger_path(None)
        assert result is not None
        assert str(result).endswith("artifacts.jsonl")


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__resolve_ledger_path_explicit(monkeypatch, posture_name, tmp_path):
    """Explicit path always returned unchanged in all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    explicit = tmp_path / "my.jsonl"
    from hi_agent.artifacts.ledger import _resolve_ledger_path
    assert _resolve_ledger_path(explicit) == explicit


# ---------------------------------------------------------------------------
# ledger._allow_legacy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,expect_allowed", [
    ("dev", True),
    ("research", False),
    ("prod", False),
])
def test__allow_legacy(monkeypatch, posture_name, expect_allowed, tmp_path):
    """Posture-matrix test for _allow_legacy.

    dev: tenantless artifact passes through.
    research/prod: tenantless artifact is denied (None returned).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.artifacts.contracts import Artifact
    from hi_agent.artifacts.ledger import ArtifactLedger

    ledger_path = None if posture_name == "dev" else (tmp_path / "artifacts.jsonl")
    ledger = ArtifactLedger(ledger_path=ledger_path)
    art = Artifact(tenant_id="")

    result = ledger._allow_legacy(art, "some-tenant")
    if expect_allowed:
        assert result is art
    else:
        assert result is None


# ---------------------------------------------------------------------------
# ledger._tenant_visible
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,tenantless_visible", [
    ("dev", True),
    ("research", False),
    ("prod", False),
])
def test__tenant_visible(monkeypatch, posture_name, tenantless_visible, tmp_path):
    """Posture-matrix test for _tenant_visible.

    dev: tenantless artifact is visible.
    research/prod: tenantless artifact is hidden.
    Matching tenant_id is always visible.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.artifacts.contracts import Artifact
    from hi_agent.artifacts.ledger import ArtifactLedger

    ledger_path = None if posture_name == "dev" else (tmp_path / "artifacts.jsonl")
    ledger = ArtifactLedger(ledger_path=ledger_path)

    # Tenantless artifact
    art_empty = Artifact(tenant_id="")
    assert ledger._tenant_visible(art_empty, "some-tenant") is tenantless_visible

    # Matching tenant is always visible
    art_match = Artifact(tenant_id="t-abc")
    assert ledger._tenant_visible(art_match, "t-abc") is True


# ---------------------------------------------------------------------------
# ArtifactRegistry.__init__
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name,should_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test___init__(monkeypatch, posture_name, should_raise):
    """Posture-matrix test for ArtifactRegistry.__init__.

    dev: in-memory registry is allowed.
    research/prod: in-memory registry raises ValueError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.artifacts.registry import ArtifactRegistry

    if should_raise:
        with pytest.raises(ValueError, match="in-memory"):
            ArtifactRegistry()
    else:
        registry = ArtifactRegistry()
        assert registry is not None
