"""Smoke test: hi_agent.runtime_adapter.consistency importable and instantiable."""
import pytest


@pytest.mark.smoke
def test_consistency_issue_importable():
    """ConsistencyIssue can be imported without error."""
    from hi_agent.runtime_adapter.consistency import ConsistencyIssue

    assert ConsistencyIssue is not None


@pytest.mark.smoke
def test_in_memory_consistency_journal_instantiable():
    """InMemoryConsistencyJournal can be instantiated with no args."""
    from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal

    journal = InMemoryConsistencyJournal()
    assert journal is not None


@pytest.mark.smoke
def test_in_memory_consistency_journal_list_issues_empty():
    """InMemoryConsistencyJournal.list_issues returns empty list initially."""
    from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal

    journal = InMemoryConsistencyJournal()
    assert journal.list_issues() == []


@pytest.mark.smoke
def test_file_backed_consistency_journal_importable():
    """FileBackedConsistencyJournal can be imported without error."""
    from hi_agent.runtime_adapter.consistency import FileBackedConsistencyJournal

    assert FileBackedConsistencyJournal is not None


@pytest.mark.smoke
def test_consistency_issue_construction():
    """ConsistencyIssue dataclass can be constructed."""
    from hi_agent.runtime_adapter.consistency import ConsistencyIssue

    issue = ConsistencyIssue(
        operation="open_stage",
        context={"stage_id": "s1"},
        error="backend failure",
    )
    assert issue.operation == "open_stage"
    assert issue.context == {"stage_id": "s1"}
    assert issue.error == "backend failure"
