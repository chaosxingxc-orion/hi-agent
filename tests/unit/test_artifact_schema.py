"""Unit tests for Artifact schema extensions and new research artifact types.

Wave 8 / P2.7
"""
from __future__ import annotations

from hi_agent.artifacts.contracts import (
    Artifact,
    CitationArtifact,
    DatasetArtifact,
    LeanProofArtifact,
    PaperArtifact,
)

# ---------------------------------------------------------------------------
# Base Artifact: new fields have correct defaults
# ---------------------------------------------------------------------------


def test_artifact_new_fields_defaults() -> None:
    a = Artifact(artifact_id="a1", artifact_type="base")
    assert a.evidence_count == 0
    assert a.content_hash == ""
    assert a.producer_run_id == ""
    assert a.producer_stage_id == ""
    assert a.producer_capability == ""
    assert a.project_id == ""


def test_artifact_to_dict_includes_new_fields() -> None:
    a = Artifact(
        artifact_id="a2",
        artifact_type="base",
        evidence_count=3,
        content_hash="abc123",
        producer_run_id="run-1",
        producer_stage_id="s1",
        producer_capability="search",
        project_id="proj-X",
    )
    d = a.to_dict()
    assert d["evidence_count"] == 3
    assert d["content_hash"] == "abc123"
    assert d["producer_run_id"] == "run-1"
    assert d["producer_stage_id"] == "s1"
    assert d["producer_capability"] == "search"
    assert d["project_id"] == "proj-X"


def test_artifact_from_dict_round_trip() -> None:
    a = Artifact(
        artifact_id="a3",
        artifact_type="base",
        evidence_count=5,
        content_hash="deadbeef",
        producer_run_id="run-99",
        project_id="proj-Y",
    )
    d = a.to_dict()
    a2 = Artifact.from_dict(d)
    assert a2.artifact_id == "a3"
    assert a2.evidence_count == 5
    assert a2.content_hash == "deadbeef"
    assert a2.producer_run_id == "run-99"
    assert a2.project_id == "proj-Y"


def test_artifact_from_dict_ignores_unknown_keys() -> None:
    d = {"artifact_id": "a4", "artifact_type": "base", "unknown_future_field": "x"}
    a = Artifact.from_dict(d)
    assert a.artifact_id == "a4"


# ---------------------------------------------------------------------------
# CitationArtifact
# ---------------------------------------------------------------------------


def test_citation_artifact_type_set() -> None:
    c = CitationArtifact(artifact_id="c1")
    assert c.artifact_type == "citation"


def test_citation_artifact_fields() -> None:
    c = CitationArtifact(
        artifact_id="c2",
        paper_id="p-001",
        doi="10.1000/xyz",
        authors=["Alice", "Bob"],
        year=2024,
        venue="NeurIPS",
    )
    assert c.paper_id == "p-001"
    assert c.doi == "10.1000/xyz"
    assert c.authors == ["Alice", "Bob"]
    assert c.year == 2024
    assert c.venue == "NeurIPS"


def test_citation_artifact_to_dict() -> None:
    c = CitationArtifact(artifact_id="c3", paper_id="p-002")
    d = c.to_dict()
    assert d["artifact_type"] == "citation"
    assert d["paper_id"] == "p-002"


# ---------------------------------------------------------------------------
# PaperArtifact
# ---------------------------------------------------------------------------


def test_paper_artifact_type_set() -> None:
    p = PaperArtifact(artifact_id="p1")
    assert p.artifact_type == "paper"


def test_paper_artifact_fields() -> None:
    p = PaperArtifact(
        artifact_id="p2",
        paper_id="paper-123",
        title="Some Title",
        abstract="An abstract.",
        local_path="/papers/paper-123.pdf",
    )
    assert p.paper_id == "paper-123"
    assert p.title == "Some Title"
    assert p.abstract == "An abstract."
    assert p.local_path == "/papers/paper-123.pdf"


# ---------------------------------------------------------------------------
# DatasetArtifact
# ---------------------------------------------------------------------------


def test_dataset_artifact_type_set() -> None:
    d = DatasetArtifact(artifact_id="d1")
    assert d.artifact_type == "dataset"


def test_dataset_artifact_auto_hashes_content() -> None:
    import hashlib
    import json

    content = {"rows": [1, 2, 3]}
    d = DatasetArtifact(artifact_id="d2", content=content)
    expected = hashlib.sha256(
        json.dumps(content, sort_keys=True, default=str).encode()
    ).hexdigest()
    assert d.content_hash == expected


def test_dataset_artifact_does_not_override_existing_hash() -> None:
    d = DatasetArtifact(artifact_id="d3", content={"x": 1}, content_hash="existing-hash")
    assert d.content_hash == "existing-hash"


# ---------------------------------------------------------------------------
# LeanProofArtifact
# ---------------------------------------------------------------------------


def test_lean_proof_artifact_type_set() -> None:
    lp = LeanProofArtifact(artifact_id="lp1")
    assert lp.artifact_type == "lean_proof"


def test_lean_proof_artifact_fields() -> None:
    lp = LeanProofArtifact(
        artifact_id="lp2",
        theorem_name="MyTheorem",
        lean_file_path="/proofs/my.lean",
        proof_status="verified",
    )
    assert lp.theorem_name == "MyTheorem"
    assert lp.lean_file_path == "/proofs/my.lean"
    assert lp.proof_status == "verified"


def test_lean_proof_default_status_unverified() -> None:
    lp = LeanProofArtifact(artifact_id="lp3")
    assert lp.proof_status == "unverified"
