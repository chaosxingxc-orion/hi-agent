"""Test backward compat: old import path works with DeprecationWarning."""
from __future__ import annotations

import warnings


def test_old_import_path_warns():
    """Importing CitationArtifact from hi_agent.artifacts.contracts emits DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from hi_agent.artifacts import contracts
        _citation_artifact = contracts.CitationArtifact
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "Expected DeprecationWarning"
    assert "research_overlay" in str(dep_warns[0].message)
