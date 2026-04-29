"""Pytest global test environment configuration."""

from __future__ import annotations

import pytest

# Prevent accidentally-added root-level test_*.py files from being collected.
# All tests must live in tests/unit/, tests/integration/, or tests/e2e/.
collect_ignore_glob = ["test_*.py"]


@pytest.fixture
def fallback_explicit(monkeypatch):
    """Explicitly enable heuristic fallback for tests that require it.

    Use instead of global os.environ.setdefault. Tests must opt-in via this
    fixture so strict-mode tests are not silently affected.
    """
    monkeypatch.setenv("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")
