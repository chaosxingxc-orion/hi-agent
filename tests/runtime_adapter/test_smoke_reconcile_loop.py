"""Smoke test: hi_agent.runtime_adapter.reconcile_loop importable and instantiable."""
import pytest


@pytest.mark.smoke
def test_reconcile_loop_importable():
    """ReconcileLoop can be imported without error."""
    from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoop

    assert ReconcileLoop is not None


@pytest.mark.smoke
def test_reconcile_loop_report_importable():
    """ReconcileLoopReport dataclass can be imported without error."""
    from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoopReport

    assert ReconcileLoopReport is not None


@pytest.mark.smoke
def test_reconcile_loop_report_construction():
    """ReconcileLoopReport can be constructed with all required fields."""
    from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoopReport

    report = ReconcileLoopReport(
        rounds=1,
        applied=0,
        failed=0,
        skipped=0,
        dead_letter_count=0,
    )
    assert report.rounds == 1


@pytest.mark.smoke
def test_reconcile_loop_instantiable():
    """ReconcileLoop can be instantiated with a backend and journal object."""
    from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal
    from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoop

    journal = InMemoryConsistencyJournal()

    class _NoopBackend:
        pass

    loop = ReconcileLoop(
        _NoopBackend(),
        journal,
        sleep_fn=lambda _: None,  # avoid real sleeping in smoke tests
    )
    assert loop is not None


@pytest.mark.smoke
def test_reconcile_loop_rejects_invalid_max_issue_retries():
    """ReconcileLoop raises ValueError for max_issue_retries < 1."""
    from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal
    from hi_agent.runtime_adapter.reconcile_loop import ReconcileLoop

    with pytest.raises(ValueError):
        ReconcileLoop(object(), InMemoryConsistencyJournal(), max_issue_retries=0)
