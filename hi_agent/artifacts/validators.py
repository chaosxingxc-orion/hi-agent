"""Platform-level artifact validation utilities."""
from __future__ import annotations

import hashlib
import json as _json
from dataclasses import dataclass
from pathlib import Path

from hi_agent.artifacts.contracts import CitationArtifact, DatasetArtifact


@dataclass
class ValidationResult:
    """Result of an artifact validation check."""

    valid: bool
    errors: list[str]


class CitationValidator:
    """Validates citations against local paper meta registry.

    A citation is valid when a corresponding papers/{paper_id}/meta.json file
    exists under the workspace root.  This enforces the platform convention
    that citations must refer to locally registered papers.
    """

    def validate(self, citation: CitationArtifact, workspace_root: Path) -> ValidationResult:
        """Validate a citation against the local paper meta registry.

        Args:
            citation: The citation artifact to validate.
            workspace_root: Workspace root directory that contains the papers/ tree.

        Returns:
            ValidationResult with valid=True if no errors found.
        """
        errors: list[str] = []
        if not citation.paper_id:
            errors.append("citation.paper_id is empty")
        else:
            meta_path = workspace_root / "papers" / citation.paper_id / "meta.json"
            if not meta_path.exists():
                errors.append(
                    f"local paper meta not found: {meta_path}. "
                    "Citations must refer to locally registered papers."
                )
        return ValidationResult(valid=len(errors) == 0, errors=errors)


class DatasetArtifactValidator:
    """Validates dataset artifact content hash integrity."""

    def validate(self, artifact: DatasetArtifact) -> ValidationResult:
        """Validate a dataset artifact's content hash.

        Args:
            artifact: The dataset artifact to validate.

        Returns:
            ValidationResult with valid=True if the content_hash matches
            the computed sha256 of the content, or if either is absent.
        """
        errors: list[str] = []
        if artifact.content and artifact.content_hash:
            expected = hashlib.sha256(
                _json.dumps(artifact.content, sort_keys=True, default=str).encode()
            ).hexdigest()
            if expected != artifact.content_hash:
                errors.append(
                    f"Dataset content_hash mismatch: stored {artifact.content_hash!r} "
                    f"!= computed {expected!r}"
                )
        return ValidationResult(valid=len(errors) == 0, errors=errors)
