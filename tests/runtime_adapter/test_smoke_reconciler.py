"""Smoke test: hi_agent.runtime_adapter.reconciler importable and instantiable."""

import pytest


@pytest.mark.smoke
def test_consistency_reconciler_importable():
    """ConsistencyReconciler can be imported without error."""
    from hi_agent.runtime_adapter.reconciler import ConsistencyReconciler

    assert ConsistencyReconciler is not None


@pytest.mark.smoke
def test_consistency_reconcile_report_importable():
    """ConsistencyReconcileReport dataclass can be imported without error."""
    from hi_agent.runtime_adapter.reconciler import ConsistencyReconcileReport

    assert ConsistencyReconcileReport is not None


@pytest.mark.smoke
def test_consistency_issue_status_importable():
    """ConsistencyIssueStatus dataclass can be imported without error."""
    from hi_agent.runtime_adapter.reconciler import ConsistencyIssueStatus

    assert ConsistencyIssueStatus is not None


@pytest.mark.smoke
def test_consistency_reconciler_instantiable():
    """ConsistencyReconciler can be instantiated with a backend object."""
    from hi_agent.runtime_adapter.reconciler import ConsistencyReconciler

    class _NoopBackend:
        pass

    reconciler = ConsistencyReconciler(_NoopBackend())
    assert reconciler is not None


@pytest.mark.smoke
def test_consistency_reconciler_reconcile_empty_journal():
    """ConsistencyReconciler.reconcile returns a zero-count report for an empty journal."""
    from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal
    from hi_agent.runtime_adapter.reconciler import ConsistencyReconciler

    reconciler = ConsistencyReconciler(object())
    report = reconciler.reconcile(InMemoryConsistencyJournal())
    assert report.total == 0
    assert report.applied == 0
    assert report.failed == 0
