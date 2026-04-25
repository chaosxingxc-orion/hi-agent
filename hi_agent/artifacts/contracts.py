"""Business-neutral artifact contracts for typed evidence and data flow.

These are platform-level data containers.  Business agents produce and
consume artifacts through the capability/harness layer — the artifact
types themselves carry no domain-specific semantics.

Stable contract fields: artifact_id, artifact_type, producer_action_id,
source_refs, metadata, provenance, upstream_artifact_ids, created_at, content
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


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
    # Defaults empty for backward compatibility with existing JSON artifacts.
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    team_space_id: str = ""
    # Wave 8 / P2.2: producer provenance and content integrity fields
    evidence_count: int = 0
    content_hash: str = ""
    producer_run_id: str = ""
    producer_stage_id: str = ""
    producer_capability: str = ""

    def __hash__(self) -> int:  # identity by artifact_id; mutable fields excluded
        """Hash by artifact_id; mutable fields excluded."""
        return hash(self.artifact_id)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this artifact."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        """Construct an artifact from a plain dict, ignoring unknown keys."""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ResourceArtifact(Artifact):
    """A discovered resource (URL, API endpoint, etc.)."""

    url: str = ""
    title: str = ""
    snippet: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'resource'."""
        self.artifact_type = "resource"


@dataclass
class DocumentArtifact(Artifact):
    """Extracted document content."""

    url: str = ""
    title: str = ""
    text: str = ""
    word_count: int = 0

    def __post_init__(self) -> None:
        """Set artifact_type to 'document'."""
        self.artifact_type = "document"


@dataclass
class StructuredDataArtifact(Artifact):
    """Typed structured data (JSON, table, etc.)."""

    schema_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set artifact_type to 'structured_data'."""
        self.artifact_type = "structured_data"


@dataclass
class EvidenceArtifact(Artifact):
    """A piece of evidence supporting or contradicting a claim."""

    claim: str = ""
    evidence_type: str = "direct"  # direct | indirect | counter
    source_id: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'evidence'."""
        self.artifact_type = "evidence"


@dataclass
class EvaluationArtifact(Artifact):
    """Result of an evaluation pass."""

    score: float = 0.0
    passed: bool = False
    criteria: dict[str, bool] = field(default_factory=dict)
    feedback: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'evaluation'."""
        self.artifact_type = "evaluation"


# Wave 8 / P2.2: Research-domain artifact types for downstream platform.


class CapabilityPolicyError(Exception):
    """Raised when a capability policy constraint is violated.

    For example, when provenance_required=True but the output carries no
    provenance dict, or when source_reference_policy='required' but
    source_refs is empty.
    """


@dataclass
class CitationArtifact(Artifact):
    """A bibliographic citation with paper reference."""

    paper_id: str = ""
    doi: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    venue: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'citation'."""
        self.artifact_type = "citation"


@dataclass
class PaperArtifact(Artifact):
    """A research paper artifact."""

    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    local_path: str = ""

    def __post_init__(self) -> None:
        """Set artifact_type to 'paper'."""
        self.artifact_type = "paper"


@dataclass
class DatasetArtifact(Artifact):
    """A dataset artifact."""

    dataset_id: str = ""
    schema_description: str = ""
    row_count: int = 0

    def __post_init__(self) -> None:
        """Set artifact_type to 'dataset' and auto-compute content_hash if empty."""
        self.artifact_type = "dataset"
        if self.content and not self.content_hash:
            import hashlib
            import json as _json

            self.content_hash = hashlib.sha256(
                _json.dumps(self.content, sort_keys=True, default=str).encode()
            ).hexdigest()


@dataclass
class LeanProofArtifact(Artifact):
    """A Lean 4 formal proof artifact."""

    theorem_name: str = ""
    lean_file_path: str = ""
    proof_status: str = "unverified"  # "verified" | "partial" | "unverified"

    def __post_init__(self) -> None:
        """Set artifact_type to 'lean_proof'."""
        self.artifact_type = "lean_proof"
