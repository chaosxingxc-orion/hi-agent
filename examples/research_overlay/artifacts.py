"""Research-domain artifact types for the research-intelligence overlay.

These classes extend the platform Artifact base with fields specific to
academic research workflows (citations, papers, formal proofs).  They are
intentionally kept outside hi_agent/ core so that the platform remains
domain-neutral.

Reference pattern for domain-specific artifact extensions.

Usage::

    from examples.research_overlay.artifacts import CitationArtifact, PaperArtifact

Deprecated import path (removed in Wave 12)::

    from hi_agent.artifacts.contracts import CitationArtifact  # DeprecationWarning
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hi_agent.artifacts.contracts import Artifact


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
class LeanProofArtifact(Artifact):
    """A Lean 4 formal proof artifact."""

    theorem_name: str = ""
    lean_file_path: str = ""
    proof_status: str = "unverified"  # "verified" | "partial" | "unverified"

    def __post_init__(self) -> None:
        """Set artifact_type to 'lean_proof'."""
        self.artifact_type = "lean_proof"
