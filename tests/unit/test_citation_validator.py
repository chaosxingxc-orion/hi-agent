"""Unit tests for PaperReferenceValidator and DatasetArtifactValidator.

Wave 8 / P2.7
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from examples.research_overlay.artifacts import CitationArtifact
from hi_agent.artifacts.contracts import DatasetArtifact
from hi_agent.artifacts.validators import DatasetArtifactValidator, PaperReferenceValidator

# ---------------------------------------------------------------------------
# PaperReferenceValidator
# ---------------------------------------------------------------------------


def test_missing_paper_meta(tmp_path: Path) -> None:
    """Citation with paper_id that has no meta.json on disk is invalid."""
    validator = PaperReferenceValidator()
    citation = CitationArtifact(paper_id="paper-123")
    result = validator.validate(citation, workspace_root=tmp_path)
    assert not result.valid
    assert any("paper-123" in e for e in result.errors)


def test_existing_paper_meta(tmp_path: Path) -> None:
    """Citation with existing meta.json on disk is valid."""
    (tmp_path / "papers" / "paper-123").mkdir(parents=True)
    (tmp_path / "papers" / "paper-123" / "meta.json").write_text('{"title": "Test"}')
    validator = PaperReferenceValidator()
    citation = CitationArtifact(paper_id="paper-123")
    result = validator.validate(citation, workspace_root=tmp_path)
    assert result.valid
    assert result.errors == []


def test_empty_paper_id_invalid(tmp_path: Path) -> None:
    """Citation with empty paper_id is invalid regardless of filesystem."""
    validator = PaperReferenceValidator()
    citation = CitationArtifact(paper_id="")
    result = validator.validate(citation, workspace_root=tmp_path)
    assert not result.valid
    assert any("paper_id" in e for e in result.errors)


# ---------------------------------------------------------------------------
# DatasetArtifactValidator
# ---------------------------------------------------------------------------


def test_dataset_valid_hash(tmp_path: Path) -> None:
    """Dataset with matching content_hash is valid."""
    content = {"rows": [1, 2, 3], "cols": ["a", "b"]}
    expected_hash = hashlib.sha256(
        json.dumps(content, sort_keys=True, default=str).encode()
    ).hexdigest()
    artifact = DatasetArtifact(artifact_id="d1", content=content, content_hash=expected_hash)
    result = DatasetArtifactValidator().validate(artifact)
    assert result.valid


def test_dataset_invalid_hash() -> None:
    """Dataset with wrong content_hash is invalid."""
    content = {"rows": [1, 2, 3]}
    artifact = DatasetArtifact(artifact_id="d2", content=content, content_hash="wrong-hash")
    result = DatasetArtifactValidator().validate(artifact)
    assert not result.valid
    assert any("mismatch" in e for e in result.errors)


def test_dataset_no_content_always_valid() -> None:
    """Dataset with no content passes validation (nothing to verify)."""
    artifact = DatasetArtifact(artifact_id="d3", content=None, content_hash="any")
    result = DatasetArtifactValidator().validate(artifact)
    assert result.valid


def test_dataset_no_hash_always_valid() -> None:
    """Dataset with content but no content_hash passes validation (opt-in check)."""
    artifact = DatasetArtifact(artifact_id="d4", content={"x": 1}, content_hash="")
    result = DatasetArtifactValidator().validate(artifact)
    assert result.valid
