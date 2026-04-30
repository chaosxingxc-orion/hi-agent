"""Posture-matrix coverage for identity contracts (AX-B B5).

Covers:
  hi_agent/contracts/identity.py — deterministic_id

Test function names are test_<function_name>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture

# ---------------------------------------------------------------------------
# deterministic_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_deterministic_id_importable_under_posture(monkeypatch, posture_name):
    """deterministic_id must be importable and callable under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.identity import deterministic_id

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    result = deterministic_id("tenant-1", "project-1", "run-1")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_deterministic_id_is_deterministic_under_posture(monkeypatch, posture_name):
    """deterministic_id returns same value for same inputs under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.identity import deterministic_id

    id1 = deterministic_id("a", "b", "c")
    id2 = deterministic_id("a", "b", "c")
    assert id1 == id2


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_deterministic_id_differs_for_different_inputs_under_posture(
    monkeypatch, posture_name
):
    """deterministic_id returns different values for different inputs under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.identity import deterministic_id

    id1 = deterministic_id("a", "b", "c")
    id2 = deterministic_id("a", "b", "d")
    assert id1 != id2


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_deterministic_id_is_url_safe_under_posture(monkeypatch, posture_name):
    """deterministic_id output contains only URL-safe characters under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.identity import deterministic_id

    result = deterministic_id("tenant-1", "proj/abc", "run_xyz")
    # URL-safe base64: A-Z, a-z, 0-9, - and _ only (no +, /, =)
    import re
    assert re.match(r'^[A-Za-z0-9_-]+$', result), f"Not URL-safe: {result!r}"
