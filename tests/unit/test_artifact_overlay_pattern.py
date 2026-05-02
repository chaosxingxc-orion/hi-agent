"""Test that the research overlay artifact pattern works correctly."""
from __future__ import annotations


def test_overlay_artifact_importable():
    """Research overlay artifacts are importable from their new location."""
    from examples.research_overlay.artifacts import (
        CitationArtifact,  # noqa: F401  expiry_wave: Wave 30
    )


def test_overlay_artifact_is_artifact_subclass():
    """Overlay artifacts extend the platform Artifact base."""
    from examples.research_overlay.artifacts import CitationArtifact
    from hi_agent.artifacts.contracts import Artifact
    assert issubclass(CitationArtifact, Artifact)
