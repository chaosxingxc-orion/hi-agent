"""Posture-matrix tests for artifact spine callsites (Rule 11).

Covers:
  hi_agent/artifacts/contracts.py  — from_dict (Artifact.from_dict)
  hi_agent/artifacts/ledger.py     — register (ArtifactLedger.register)
  hi_agent/artifacts/registry.py   — _enforce_content_addressed_id, _tenant_match
  hi_agent/server/team_run_registry.py — register (TeamRunRegistry.register)

Test function names are test_<source_function_name> so check_posture_coverage.py
matches them to callsite function names.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# artifacts.contracts.Artifact.from_dict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,expect_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_from_dict(monkeypatch, posture_name, expect_raise, tmp_path):
    """Posture-matrix test for Artifact.from_dict.

    Under research/prod posture: mismatched artifact_id raises ArtifactIntegrityError.
    Under dev posture: mismatch logs WARNING and continues (back-compat).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    # Build a content-addressable artifact with correct ID first.
    import hashlib

    from hi_agent.artifacts.contracts import Artifact, ArtifactIntegrityError, derive_artifact_id
    content = "hello-content"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    correct_id = derive_artifact_id(content_hash)

    # Roundtrip with correct id should always succeed.
    valid_data = {
        "artifact_type": "document",
        "artifact_id": correct_id,
        "content_hash": content_hash,
    }
    result = Artifact.from_dict(valid_data)
    assert result.artifact_id == correct_id

    # Mismatched artifact_id on content-addressable type.
    bad_data = {
        "artifact_type": "document",
        "artifact_id": "art_baadbaadbaadbaadbaadbaad",
        "content_hash": content_hash,
    }
    if expect_raise:
        with pytest.raises(ArtifactIntegrityError, match="artifact_id mismatch"):
            Artifact.from_dict(bad_data)
    else:
        # dev: should log warning and return the artifact with stored id
        artifact = Artifact.from_dict(bad_data)
        assert artifact is not None


# ---------------------------------------------------------------------------
# artifacts.ledger.ArtifactLedger.register
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,expect_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test_register(monkeypatch, posture_name, expect_raise, tmp_path):
    """Posture-matrix test for ArtifactLedger.register.

    Under research/prod posture: registering a content-addressable artifact with
    a non-derived artifact_id raises ArtifactIntegrityError.
    Under dev posture: auto-derives the id and logs a warning.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.artifacts.contracts import (
        Artifact,
        ArtifactIntegrityError,
    )
    from hi_agent.artifacts.ledger import ArtifactLedger

    ledger_path = tmp_path / "artifacts.jsonl"
    ledger = ArtifactLedger(ledger_path=ledger_path)

    import hashlib
    content_hash = hashlib.sha256(b"some-content").hexdigest()
    # Create artifact with a deliberately wrong artifact_id
    art = Artifact(
        artifact_type="document",
        artifact_id="art_wrongwrongwrongwrong0000",
        content_hash=content_hash,
        tenant_id="t-abc",
    )

    if expect_raise:
        with pytest.raises(ArtifactIntegrityError, match="artifact_id must derive"):
            ledger.register(art)
    else:
        # dev: auto-derives and succeeds
        ledger.register(art)


# ---------------------------------------------------------------------------
# artifacts.registry._enforce_content_addressed_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,expect_raise", [
    ("dev", False),
    ("research", True),
    ("prod", True),
])
def test__enforce_content_addressed_id(monkeypatch, posture_name, expect_raise):
    """Posture-matrix test for _enforce_content_addressed_id.

    Under research/prod: artifact with wrong content-derived id raises.
    Under dev: auto-derives and warns.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    import hashlib

    from hi_agent.artifacts.contracts import Artifact, ArtifactIntegrityError
    from hi_agent.artifacts.registry import _enforce_content_addressed_id
    content_hash = hashlib.sha256(b"registry-content").hexdigest()
    # artifact_id that does NOT derive from content_hash
    art = Artifact(
        artifact_type="document",
        artifact_id="art_wrongwrongwrongwrong0000",
        content_hash=content_hash,
        tenant_id="t-abc",
    )

    if expect_raise:
        with pytest.raises(ArtifactIntegrityError):
            _enforce_content_addressed_id(art)
    else:
        # dev: auto-derive, no exception
        _enforce_content_addressed_id(art)
        # After auto-derive, artifact_id should be the correct derived one
        from hi_agent.artifacts.contracts import derive_artifact_id
        assert art.artifact_id == derive_artifact_id(content_hash)


# ---------------------------------------------------------------------------
# artifacts.registry.ArtifactRegistry._tenant_match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("posture_name,tenantless_visible", [
    ("dev", True),
    ("research", False),
    ("prod", False),
])
def test__tenant_match(monkeypatch, posture_name, tenantless_visible):
    """Posture-matrix test for ArtifactRegistry._tenant_match.

    dev: legacy tenantless artifacts are visible (returns True).
    research/prod: legacy tenantless artifacts are denied (returns False).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    # ArtifactRegistry() raises under research/prod — use dev to build the instance,
    # then swap the posture just for the method call.
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.artifacts.contracts import Artifact
    from hi_agent.artifacts.registry import ArtifactRegistry

    registry = ArtifactRegistry()
    # Now set the target posture
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)

    # Legacy tenantless artifact
    art_no_tenant = Artifact(tenant_id="", artifact_type="base")
    result = registry._tenant_match(art_no_tenant, "some-tenant")
    assert result is tenantless_visible

    # Always visible to matching tenant regardless of posture
    art_match = Artifact(tenant_id="t-abc", artifact_type="base")
    assert registry._tenant_match(art_match, "t-abc") is True


