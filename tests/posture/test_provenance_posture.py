"""Posture-matrix coverage for provenance contracts (AX-B B5).

Covers:
  hi_agent/contracts/provenance.py — Provenance

Test function names are test_<contract_snake>_* so check_posture_coverage.py
can match them to contract callsites.
"""
from __future__ import annotations

import pytest
from hi_agent.config.posture import Posture


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_provenance_instantiates_under_posture(monkeypatch, posture_name):
    """Provenance must be instantiable with defaults under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.provenance import Provenance

    posture = Posture.from_env()
    assert posture == Posture(posture_name)

    prov = Provenance()
    assert prov.url == ""
    assert prov.title == ""
    assert prov.source_type == ""
    assert prov.retrieved_at == ""


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_provenance_with_values_under_posture(monkeypatch, posture_name):
    """Provenance with explicit values is valid under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.provenance import Provenance

    prov = Provenance(
        url="https://example.com/doc",
        title="Example Document",
        source_type="web",
        retrieved_at="2026-04-29T00:00:00Z",
    )
    assert prov.url == "https://example.com/doc"
    assert prov.source_type == "web"


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_provenance_source_types_under_posture(monkeypatch, posture_name):
    """Provenance accepts all documented source_type values under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts.provenance import Provenance

    for source_type in ("web", "pdf", "api", "user_input", "llm_inference"):
        prov = Provenance(source_type=source_type)
        assert prov.source_type == source_type
