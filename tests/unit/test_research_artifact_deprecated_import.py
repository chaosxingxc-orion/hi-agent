"""Test CitationArtifact import path is from research_overlay (W18: shim removed)."""
from __future__ import annotations


def test_canonical_import_path_works():
    """CitationArtifact imports cleanly from examples.research_overlay.artifacts."""
    from examples.research_overlay.artifacts import CitationArtifact

    assert CitationArtifact is not None


def test_old_import_path_raises_attribute_error():
    """After W18 shim removal, CitationArtifact not in hi_agent.artifacts.contracts."""
    import pytest

    with pytest.raises(AttributeError):
        from hi_agent.artifacts import contracts

        _ = contracts.CitationArtifact
