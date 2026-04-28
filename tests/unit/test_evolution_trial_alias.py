"""Test EvolutionTrial canonical class correctness (W18: EvolutionExperiment alias removed)."""
from __future__ import annotations


def test_evolution_trial_is_canonical():
    """EvolutionTrial imports cleanly."""
    from hi_agent.evolve.contracts import EvolutionTrial  # noqa: F401  expiry_wave: Wave 19


def test_evolution_trial_has_tenant_id():
    """EvolutionTrial carries tenant_id as required by Rule 12."""
    import dataclasses

    from hi_agent.evolve.contracts import EvolutionTrial
    field_names = {f.name for f in dataclasses.fields(EvolutionTrial)}
    assert "tenant_id" in field_names