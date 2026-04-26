"""Test EvolutionTrial/EvolutionExperiment alias correctness."""
from __future__ import annotations

import warnings


def test_evolution_trial_is_canonical():
    """EvolutionTrial imports cleanly."""
    from hi_agent.evolve.contracts import EvolutionTrial  # noqa: F401


def test_evolution_experiment_deprecated():
    """EvolutionExperiment triggers DeprecationWarning and resolves to EvolutionTrial."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import importlib

        import hi_agent.evolve.contracts as contracts
        importlib.reload(contracts)
        _ = contracts.EvolutionExperiment
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "Expected DeprecationWarning for EvolutionExperiment"
    assert "EvolutionTrial" in str(dep_warns[0].message)


def test_evolution_trial_has_tenant_id():
    """EvolutionTrial carries tenant_id as required by Rule 12."""
    import dataclasses

    from hi_agent.evolve.contracts import EvolutionTrial
    field_names = {f.name for f in dataclasses.fields(EvolutionTrial)}
    assert "tenant_id" in field_names


def test_evolution_trial_resolves_to_same_class_as_experiment():
    """EvolutionExperiment alias resolves to the same class as EvolutionTrial."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        import hi_agent.evolve.contracts as contracts
        from hi_agent.evolve.contracts import EvolutionTrial
        resolved = contracts.EvolutionExperiment
    assert resolved is EvolutionTrial