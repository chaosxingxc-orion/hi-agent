"""Integration tests for durable consistency journal persistence."""

from __future__ import annotations

from pathlib import Path

from hi_agent.runtime_adapter.consistency import (
    ConsistencyIssue,
    FileBackedConsistencyJournal,
    InMemoryConsistencyJournal,
)


def test_file_backed_journal_appends_and_lists_issues(tmp_path: Path) -> None:
    """Appended issues should be visible in memory and persisted on disk."""
    journal_path = tmp_path / "consistency.journal"
    journal = FileBackedConsistencyJournal(journal_path)

    issue = ConsistencyIssue(
        operation="mark_stage_state",
        context={"stage_id": "S1_understand", "target_state": "active"},
        error="RuntimeError: mark failed",
    )

    journal.append(issue)

    issues = journal.list_issues()
    assert issues == [issue]
    assert journal_path.exists()
    assert journal_path.read_text(encoding="utf-8").strip() != ""


def test_file_backed_journal_reloads_from_disk(tmp_path: Path) -> None:
    """Issues should survive process restarts by reloading from disk."""
    journal_path = tmp_path / "consistency.journal"
    first = FileBackedConsistencyJournal(journal_path)

    expected = ConsistencyIssue(
        operation="open_stage",
        context={"stage_id": "S1_understand"},
        error="RuntimeError: open failed",
    )
    first.append(expected)

    second_process = FileBackedConsistencyJournal(journal_path)
    second_process.append(
        ConsistencyIssue(
            operation="mark_stage_state",
            context={"stage_id": "S1_understand", "target_state": "active"},
            error="RuntimeError: mark failed",
        )
    )
    first.reload_from_disk()

    issues = first.list_issues()
    assert len(issues) == 2
    assert issues[0] == expected
    assert issues[1].operation == "mark_stage_state"


def test_file_backed_journal_size_tracks_append_and_reload(tmp_path: Path) -> None:
    """File-backed size should reflect append and reload from persisted records."""
    journal_path = tmp_path / "consistency.journal"
    first = FileBackedConsistencyJournal(journal_path)
    assert first.size() == 0

    first.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S1_understand"},
            error="RuntimeError: open failed",
        )
    )
    assert first.size() == 1

    second_process = FileBackedConsistencyJournal(journal_path)
    assert second_process.size() == 1
    second_process.append(
        ConsistencyIssue(
            operation="mark_stage_state",
            context={"stage_id": "S1_understand", "target_state": "active"},
            error="RuntimeError: mark failed",
        )
    )
    assert second_process.size() == 2

    first.reload_from_disk()
    assert first.size() == 2


def test_file_backed_journal_skips_empty_and_malformed_lines(tmp_path: Path) -> None:
    """Corrupt lines should be ignored while valid records still load."""
    journal_path = tmp_path / "consistency.journal"
    valid_line = (
        '{"operation":"open_stage","context":{"stage_id":"S1_understand"},'
        '"error":"RuntimeError: open failed"}\n'
    )
    journal_path.write_text(
        f'\nnot-json\n{valid_line}{{"operation":"bad-context","context":"wrong","error":"oops"}}\n',
        encoding="utf-8",
    )

    journal = FileBackedConsistencyJournal(journal_path)

    issues = journal.list_issues()
    assert len(issues) == 1
    assert issues[0].operation == "open_stage"
    assert issues[0].context["stage_id"] == "S1_understand"


def test_in_memory_journal_list_remains_snapshot_compatible() -> None:
    """In-memory list behavior should stay copy-on-read compatible."""
    journal = InMemoryConsistencyJournal()
    issue = ConsistencyIssue(
        operation="record_task_view",
        context={"task_view_id": "tv-1"},
        error="err",
    )
    journal.append(issue)

    first_read = journal.list_issues()
    first_read.append(
        ConsistencyIssue(
            operation="open_stage",
            context={"stage_id": "S1_understand"},
            error="other",
        )
    )

    assert journal.list_issues() == [issue]


def test_in_memory_journal_size_tracks_appends() -> None:
    """In-memory size should track appended records."""
    journal = InMemoryConsistencyJournal()
    assert journal.size() == 0

    journal.append(
        ConsistencyIssue(
            operation="record_task_view",
            context={"task_view_id": "tv-1"},
            error="err",
        )
    )
    assert journal.size() == 1
