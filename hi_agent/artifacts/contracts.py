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
    # run_id spine field for direct run traceability (Rule 12).
    # Default "" for backward compatibility.
    run_id: str = ""

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
        if self.content and not self.content_hash:
            import hashlib
            import json as _json

            self.content_hash = hashlib.sha256(
                _json.dumps(self.content, sort_keys=True, default=str).encode()
            ).hexdigest()


# CitationArtifact, PaperArtifact, and LeanProofArtifact have moved to
# examples.research_overlay.artifacts.  They are research-domain types and do
# not belong in the platform artifact module.  A backward-compat shim below
# forwards attribute access (removed in a future release).


def __getattr__(name: str) -> object:
    """Backward-compat shim for research-domain artifact classes.

    CitationArtifact, PaperArtifact, and LeanProofArtifact have moved to
    ``examples.research_overlay.artifacts``.  Import them from there instead.
    This shim emits DeprecationWarning and will be removed in a future release.
    """
    _overlay_classes = {"CitationArtifact", "PaperArtifact", "LeanProofArtifact"}
    if name in _overlay_classes:
        import importlib
        import warnings

        warnings.warn(
            f"{name} has moved to examples.research_overlay.artifacts. "
            "Import it from there instead. This compatibility shim will be "
            "removed in Wave 15.",
            DeprecationWarning,
            stacklevel=2,
        )
        overlay = importlib.import_module("examples.research_overlay.artifacts")
        return getattr(overlay, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
