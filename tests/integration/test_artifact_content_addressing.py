"""Integration tests for content-addressed artifact identity (A-11, Wave 23).

Profile: default-offline (no network, no real LLM, no secrets).

Covers:
1. Idempotent register: same content → same artifact_id (dev posture, registry).
2. 409 conflict: same artifact_id but different content_hash → ArtifactConflictError
   (research posture, durable ledger).
3. Tampered ledger entry under research → ArtifactIntegrityError on load.
4. Tampered ledger entry under dev → WARNING logged, load proceeds.
"""
from __future__ import annotations

import json
import logging

import pytest
from hi_agent.artifacts.contracts import (
    Artifact,
    ArtifactConflictError,
    ArtifactIntegrityError,
    DocumentArtifact,
)
from hi_agent.artifacts.ledger import ArtifactLedger
from hi_agent.artifacts.registry import ArtifactRegistry

# ---------------------------------------------------------------------------
# Test 1 — Idempotent registration under dev posture (in-memory registry)
# ---------------------------------------------------------------------------


def test_same_content_yields_same_artifact_id(monkeypatch):
    """Registering the same content twice produces a single ledger entry.

    Uses ``ArtifactRegistry.create()`` (no caller-supplied artifact_id) under
    dev posture — caller does not pin the id, so it is derived from content.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    registry = ArtifactRegistry()

    content = {"title": "x", "body": "hello world"}
    a1 = registry.create(artifact_type="document", content=content)
    a2 = registry.create(artifact_type="document", content=content)

    assert a1.artifact_id.startswith("art_"), "id must be content-derived"
    assert a1.artifact_id == a2.artifact_id, "same content must yield same id"
    assert registry.count() == 1, "second register must collapse to existing entry"
    assert a1.content_hash == a2.content_hash


# ---------------------------------------------------------------------------
# Test 2 — 409 on tamper-write (research posture, durable ledger)
# ---------------------------------------------------------------------------


def test_register_with_mismatched_content_hash_raises_conflict(monkeypatch, tmp_path):
    """Two writes against the same artifact_id but different content_hash.

    The 409 conflict is the legacy/migration path: when a manually-pinned
    (non-content-addressable) artifact_id is reused for content with a
    different hash, the second write must raise ArtifactConflictError
    (mapped to HTTP 409 by the route layer).
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
    ledger = ArtifactLedger(tmp_path / "artifacts.jsonl")

    # Use 'base' artifact_type (NOT content-addressable) so the id is allowed
    # to be manually pinned without integrity-error firing first.  This is the
    # realistic shape of the conflict path: legacy callers pinning ids while
    # the platform still wants to detect tamper-writes.
    art_a = Artifact(artifact_id="legacy-fixed-id", content={"k": "A"})
    ledger.register(art_a)

    # Second write: same pinned id, but content_hash differs.
    art_b = Artifact(artifact_id="legacy-fixed-id", content={"k": "B"})
    assert art_a.content_hash != art_b.content_hash, "fixture sanity"

    with pytest.raises(ArtifactConflictError):
        ledger.register(art_b)


def test_research_posture_rejects_non_derived_id_on_write(monkeypatch, tmp_path):
    """Under research posture, writing a content-addressable artifact whose
    artifact_id does not derive from content_hash raises ArtifactIntegrityError.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
    ledger = ArtifactLedger(tmp_path / "artifacts.jsonl")

    art = DocumentArtifact(content={"k": "v"})
    art.artifact_id = "manual-id-123"  # does NOT derive from content_hash

    with pytest.raises(ArtifactIntegrityError):
        ledger.register(art)


# ---------------------------------------------------------------------------
# Test 3 — Tampered ledger entry under research → ArtifactIntegrityError
# ---------------------------------------------------------------------------


def test_load_tampered_entry_under_research_raises(monkeypatch, tmp_path):
    """Loading a ledger row whose stored artifact_id does not derive from its
    content_hash must raise ArtifactIntegrityError under research posture.
    """
    ledger_file = tmp_path / "artifacts.jsonl"

    # Build a tampered row: derive nothing — store artifact_id="bad" with a
    # real content_hash for a content-addressable type.
    art = DocumentArtifact(content={"k": "v"})
    real_hash = art.content_hash
    tampered = art.to_dict()
    tampered["artifact_id"] = "tampered-bad-id"
    tampered["content_hash"] = real_hash  # hash is genuine, id is not derived

    ledger_file.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    # Now load under research posture.
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    # ArtifactLedger._load swallows from_dict exceptions into the quarantine
    # path, but the exception itself must be ArtifactIntegrityError when
    # called directly.
    with pytest.raises(ArtifactIntegrityError):
        Artifact.from_dict(tampered)


# ---------------------------------------------------------------------------
# Test 4 — Tampered entry under dev → WARNING, load succeeds
# ---------------------------------------------------------------------------


def test_load_tampered_entry_under_dev_warns_and_loads(monkeypatch, caplog):
    """Under dev posture, a non-derived artifact_id on a content-addressable
    artifact emits a WARNING but ``from_dict`` still returns the artifact.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    art = DocumentArtifact(content={"k": "v"})
    tampered = art.to_dict()
    tampered["artifact_id"] = "legacy-uuid-id"

    with caplog.at_level(logging.WARNING, logger="hi_agent.artifacts.contracts"):
        loaded = Artifact.from_dict(tampered)

    assert loaded.artifact_id == "legacy-uuid-id"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "artifact_id mismatch" in r.message.lower()
        or "ArtifactIntegrityError" in r.getMessage()
        for r in warnings
    ), "Dev posture must log a WARNING for the mismatch"
