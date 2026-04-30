"""Business-neutral artifact contracts for typed evidence and data flow.

These are platform-level data containers.  Business agents produce and
consume artifacts through the capability/harness layer — the artifact
types themselves carry no domain-specific semantics.

Stable contract fields: artifact_id, artifact_type, producer_action_id,
source_refs, metadata, provenance, upstream_artifact_ids, created_at, content
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)

# A-11: artifact_type values whose identity must be derived from content_hash.
# Ephemeral types (e.g. "trace", "evaluation", "base") keep uuid-based ids.
CONTENT_ADDRESSABLE_TYPES: frozenset[str] = frozenset(
    {"document", "resource", "structured_data", "evidence"}
)


class ArtifactIntegrityError(Exception):
    """Raised when a stored artifact_id does not match its content-derived id.

    Triggered under research/prod posture by ``Artifact.from_dict`` and by
    ``ArtifactRegistry`` write paths when a content-addressable artifact carries
    a non-derived ``artifact_id``.
    """


class ArtifactConflictError(Exception):
    """Raised on a write that would replace an existing artifact_id with a
    different content_hash.  Maps to HTTP 409 at the route layer.
    """


def derive_artifact_id(content_hash: str) -> str:
    """Return the content-addressed artifact id for a given content_hash.

    Format: ``art_<first 24 hex chars of content_hash>``.  24 hex chars =
    96 bits of collision resistance, sufficient for in-corpus uniqueness.
    """
    if not content_hash:
        raise ValueError("derive_artifact_id requires a non-empty content_hash")
    return f"art_{content_hash[:24]}"


@dataclass
class Artifact:
    """Base artifact produced by a capability action."""

    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    artifact_type: str = "base"
    producer_action_id: str = ""
    confidence: float = 0.0
    source_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    upstream_artifact_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    content: Any = None
    project_id: str = ""
    # CO-5: tenant/user/session/team spine fields for cross-run scoping.
    tenant_id: str = ""  # scope: process-internal — artifact; populated from exec_ctx
    user_id: str = ""
    session_id: str = ""
    team_space_id: str = ""
    # Wave 8 / P2.2: producer provenance and content integrity fields
    evidence_count: int = 0
    content_hash: str = ""
    producer_run_id: str = ""
    producer_stage_id: str = ""
    producer_capability: str = ""
    # run_id spine field for direct run traceability (Rule 12).
    # Default "" for backward compatibility.
    run_id: str = ""

    def __post_init__(self) -> None:
        """Auto-compute content_hash for all artifact types when content is present."""
        if self.content and not self.content_hash:
            self.content_hash = hashlib.sha256(
                _json.dumps(self.content, sort_keys=True, default=str).encode()
            ).hexdigest()

    def __hash__(self) -> int:  # identity by artifact_id; mutable fields excluded
        """Hash by artifact_id; mutable fields excluded."""
        return hash(self.artifact_id)

    @property
    def is_content_addressable(self) -> bool:
        """True when this artifact's identity must derive from content_hash.

        Driven by ``artifact_type`` membership in ``CONTENT_ADDRESSABLE_TYPES``
        (Wave 23 / A-11).
        """
        return self.artifact_type in CONTENT_ADDRESSABLE_TYPES

    @property
    def expected_artifact_id(self) -> str:
        """Content-derived artifact_id for content-addressable types.

        For content-addressable types (``document``, ``resource``,
        ``structured_data``, ``evidence``) this returns
        ``f"art_{content_hash[:24]}"``.  For ephemeral types (e.g. ``trace``,
        ``evaluation``, ``base``) this returns the current ``artifact_id`` —
        i.e. the uuid-derived value.  Callers that need to *enforce* derivation
        should gate on ``is_content_addressable``.
        """
        if self.is_content_addressable and self.content_hash:
            return derive_artifact_id(self.content_hash)
        return self.artifact_id

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this artifact."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        """Construct an artifact from a plain dict, ignoring unknown keys.

        A-11: for content-addressable artifact types under research/prod
        posture, the stored ``artifact_id`` is verified against the
        content-derived id.  Mismatch raises :class:`ArtifactIntegrityError`.
        Under dev posture a WARNING is logged and load proceeds (back-compat
        for legacy ledger entries).
        """
        known = set(cls.__dataclass_fields__)
        artifact = cls(**{k: v for k, v in data.items() if k in known})

        if artifact.is_content_addressable and artifact.content_hash:
            expected = artifact.expected_artifact_id
            if artifact.artifact_id != expected:
                from hi_agent.config.posture import Posture

                posture = Posture.from_env()
                msg = (
                    f"artifact_id mismatch on load: stored={artifact.artifact_id!r} "
                    f"expected={expected!r} artifact_type={artifact.artifact_type!r} "
                    f"content_hash={artifact.content_hash[:16]}..."
                )
                if posture.is_strict:
                    raise ArtifactIntegrityError(msg)
                _logger.warning("ArtifactIntegrityError (dev): %s", msg)
        return artifact


@dataclass
class ResourceArtifact(Artifact):
    """A discovered resource (URL, API endpoint, etc.)."""

    url: str = ""
    title: str = ""
    snippet: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'resource' and compute content_hash."""
        self.artifact_type = "resource"
        super().__post_init__()


@dataclass
class DocumentArtifact(Artifact):
    """Extracted document content."""

    url: str = ""
    title: str = ""
    text: str = ""
    word_count: int = 0

    def __post_init__(self) -> None:
        """Set artifact_type to 'document' and compute content_hash."""
        self.artifact_type = "document"
        super().__post_init__()


@dataclass
class StructuredDataArtifact(Artifact):
    """Typed structured data (JSON, table, etc.)."""

    schema_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set artifact_type to 'structured_data' and compute content_hash."""
        self.artifact_type = "structured_data"
        super().__post_init__()


@dataclass
class EvidenceArtifact(Artifact):
    """A piece of evidence supporting or contradicting a claim."""

    claim: str = ""
    evidence_type: str = "direct"  # direct | indirect | counter
    source_id: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'evidence' and compute content_hash."""
        self.artifact_type = "evidence"
        super().__post_init__()


@dataclass
class EvaluationArtifact(Artifact):
    """Result of an evaluation pass."""

    score: float = 0.0
    passed: bool = False
    criteria: dict[str, bool] = field(default_factory=dict)
    feedback: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'evaluation' and compute content_hash."""
        self.artifact_type = "evaluation"
        super().__post_init__()


class CapabilityPolicyError(Exception):
    """Raised when a capability policy constraint is violated.

    For example, when provenance_required=True but the output carries no
    provenance dict, or when source_reference_policy='required' but
    source_refs is empty.
    """


@dataclass
class DatasetArtifact(Artifact):
    """A dataset artifact."""

    dataset_id: str = ""
    schema_description: str = ""
    row_count: int = 0

    def __post_init__(self) -> None:
        """Set artifact_type to 'dataset' and auto-compute content_hash if empty."""
        self.artifact_type = "dataset"
        super().__post_init__()


