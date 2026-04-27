"""Test RunRetrospective/RunPostmortem alias correctness."""
from __future__ import annotations

import warnings


def test_run_retrospective_is_canonical():
    """RunRetrospective imports cleanly."""
    from hi_agent.evolve.contracts import RunRetrospective  # noqa: F401  expiry_wave: Wave 17


def test_run_postmortem_deprecated():
    """RunPostmortem triggers DeprecationWarning and resolves to RunRetrospective."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import importlib

        import hi_agent.evolve.contracts as contracts
        # Reload to ensure __getattr__ is fresh
        importlib.reload(contracts)
        _ = contracts.RunPostmortem
    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "Expected DeprecationWarning for RunPostmortem"
    assert "RunRetrospective" in str(dep_warns[0].message)


def test_project_retrospective_has_outcome_assessments():
    """ProjectRetrospective uses outcome_assessments, not hypothesis_outcomes."""
    import dataclasses

    from hi_agent.evolve.contracts import ProjectRetrospective
    field_names = {f.name for f in dataclasses.fields(ProjectRetrospective)}
    assert "outcome_assessments" in field_names
    assert "hypothesis_outcomes" not in field_names


def test_project_retrospective_has_invalidated_assumptions():
    """ProjectRetrospective uses invalidated_assumptions, not failed_assumptions."""
    import dataclasses

    from hi_agent.evolve.contracts import ProjectRetrospective
    field_names = {f.name for f in dataclasses.fields(ProjectRetrospective)}
    assert "invalidated_assumptions" in field_names
    assert "failed_assumptions" not in field_names


def test_run_retrospective_has_tenant_id():
    """RunRetrospective carries tenant_id as required by Rule 12."""
    import dataclasses

    from hi_agent.evolve.contracts import RunRetrospective
    field_names = {f.name for f in dataclasses.fields(RunRetrospective)}
    assert "tenant_id" in field_names