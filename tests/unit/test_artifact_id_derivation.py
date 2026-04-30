"""Unit tests for content-addressed artifact identity (A-11, Wave 23).

Covers ``Artifact.expected_artifact_id`` and the ``derive_artifact_id`` helper
across the four content-addressable artifact types
(``document``, ``resource``, ``structured_data``, ``evidence``) plus the
non-content-addressable ``base`` and ``trace`` types.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from hi_agent.artifacts.contracts import (
    CONTENT_ADDRESSABLE_TYPES,
    Artifact,
    DocumentArtifact,
    EvidenceArtifact,
    ResourceArtifact,
    StructuredDataArtifact,
    derive_artifact_id,
)


def _expected_hash(content: object) -> str:
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, default=str).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# derive_artifact_id helper
# ---------------------------------------------------------------------------


def test_derive_artifact_id_format():
    """derive_artifact_id returns ``art_<24 hex chars>``."""
    h = "a" * 64
    assert derive_artifact_id(h) == "art_" + ("a" * 24)


def test_derive_artifact_id_truncates_to_24():
    """Length is exactly 24 hex chars regardless of input length."""
    h = "abcdef0123456789" * 4  # 64 chars
    out = derive_artifact_id(h)
    assert out.startswith("art_")
    assert len(out) == 4 + 24


def test_derive_artifact_id_rejects_empty():
    """Empty content_hash raises ValueError — derivation has no input."""
    with pytest.raises(ValueError):
        derive_artifact_id("")


# ---------------------------------------------------------------------------
# expected_artifact_id property — content-addressable types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls,kind",
    [
        (DocumentArtifact, "document"),
        (ResourceArtifact, "resource"),
        (StructuredDataArtifact, "structured_data"),
        (EvidenceArtifact, "evidence"),
    ],
)
def test_expected_artifact_id_for_content_addressable_types(cls, kind):
    """All 4 content-addressable types derive id from content_hash."""
    content = {"k": "v", "n": 1}
    art = cls(content=content)
    assert art.artifact_type == kind
    assert art.is_content_addressable is True
    assert art.content_hash == _expected_hash(content)
    assert art.expected_artifact_id == "art_" + art.content_hash[:24]


def test_content_addressable_types_membership():
    """The CONTENT_ADDRESSABLE_TYPES set covers exactly 4 kinds."""
    assert frozenset(
        {"document", "resource", "structured_data", "evidence"}
    ) == CONTENT_ADDRESSABLE_TYPES


# ---------------------------------------------------------------------------
# Non-content-addressable types — keep uuid behaviour
# ---------------------------------------------------------------------------


def test_base_artifact_keeps_uuid_id():
    """Base artifact (artifact_type='base') is NOT content-addressable."""
    art = Artifact(content={"x": 1})
    assert art.artifact_type == "base"
    assert art.is_content_addressable is False
    # expected_artifact_id falls back to the current artifact_id (uuid).
    assert art.expected_artifact_id == art.artifact_id
    # uuid hex slice has no "art_" prefix.
    assert not art.artifact_id.startswith("art_")


def test_trace_artifact_keeps_uuid_id():
    """A 'trace' artifact_type is ephemeral — uuid id, no derivation."""
    art = Artifact(artifact_type="trace", content={"event": "tick"})
    assert art.is_content_addressable is False
    # Property returns the current uuid-style id, not raising.
    assert art.expected_artifact_id == art.artifact_id


def test_evaluation_artifact_keeps_uuid_id():
    """EvaluationArtifact is not in CONTENT_ADDRESSABLE_TYPES."""
    from hi_agent.artifacts.contracts import EvaluationArtifact

    art = EvaluationArtifact(score=0.9, passed=True, content={"k": "v"})
    assert art.artifact_type == "evaluation"
    assert art.is_content_addressable is False
    assert art.expected_artifact_id == art.artifact_id


# ---------------------------------------------------------------------------
# expected_artifact_id with no content_hash
# ---------------------------------------------------------------------------


def test_content_addressable_without_hash_returns_current_id():
    """When content_hash is empty, expected_artifact_id returns artifact_id."""
    art = DocumentArtifact()  # no content → no hash
    assert art.content_hash == ""
    # Falls back to current id (uuid) rather than raising.
    assert art.expected_artifact_id == art.artifact_id
