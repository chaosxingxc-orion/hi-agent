"""Tests for JSONL-backed event store."""

from __future__ import annotations

from pathlib import Path

from hi_agent.events import (
    EventEnvelope,
    append_event,
    append_events,
    list_event_files,
    load_events,
    load_events_for_run,
)


def test_append_and_load_events_round_trip(tmp_path: Path) -> None:
    """Store should append envelopes and load them back in order."""
    event_path = tmp_path / "run-1.jsonl"
    first = EventEnvelope(
        event_type="StageOpened",
        run_id="run-1",
        payload={"stage_id": "S1"},
        timestamp="2026-04-05T10:00:00+00:00",
    )
    second = EventEnvelope(
        event_type="StageCompleted",
        run_id="run-1",
        payload={"stage_id": "S1"},
        timestamp="2026-04-05T10:00:01+00:00",
    )

    append_event(event_path, first)
    append_event(event_path, second)

    events, bad_line_count = load_events(event_path)
    assert bad_line_count == 0
    assert events == [first, second]


def test_load_events_skips_bad_lines_and_counts_them(tmp_path: Path) -> None:
    """Loader should skip malformed lines and report count."""
    event_path = tmp_path / "corrupted.jsonl"
    event_path.write_text(
        "\n".join(
            [
                '{"event_type":"A","run_id":"r1","payload":{"k":1},"timestamp":"2026-04-05T10:00:00+00:00"}',
                '{"event_type":"B","run_id":"r1","payload":{"k":2},"timestamp":"2026-04-05T10:00:01+00:00"',
                '{"event_type":"C","run_id":"r1","payload":{"k":3}}',
                "",
            ]
        ),
        encoding="utf-8",
    )

    events, bad_line_count = load_events(event_path)

    assert [event.event_type for event in events] == ["A"]
    assert bad_line_count == 2


def test_load_events_from_empty_file(tmp_path: Path) -> None:
    """Loader should return empty result for empty file."""
    event_path = tmp_path / "empty.jsonl"
    event_path.write_text("", encoding="utf-8")

    events, bad_line_count = load_events(event_path)
    assert events == []
    assert bad_line_count == 0


def test_list_event_files_returns_sorted_jsonl_files(tmp_path: Path) -> None:
    """List should return JSONL files in stable sorted order."""
    (tmp_path / "b.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "a.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("", encoding="utf-8")

    assert list_event_files(tmp_path) == [tmp_path / "a.jsonl", tmp_path / "b.jsonl"]


def test_append_events_appends_batch_in_input_order(tmp_path: Path) -> None:
    """Batch append should preserve the exact envelope input order."""
    event_path = tmp_path / "batch.jsonl"
    first = EventEnvelope(
        event_type="StageOpened",
        run_id="run-1",
        payload={"stage_id": "S1"},
        timestamp="2026-04-05T10:00:00+00:00",
    )
    second = EventEnvelope(
        event_type="StageCompleted",
        run_id="run-1",
        payload={"stage_id": "S1"},
        timestamp="2026-04-05T10:00:01+00:00",
    )
    third = EventEnvelope(
        event_type="StageOpened",
        run_id="run-2",
        payload={"stage_id": "S2"},
        timestamp="2026-04-05T10:00:02+00:00",
    )

    append_event(event_path, first)
    append_events(event_path, [second, third])

    events, bad_line_count = load_events(event_path)
    assert bad_line_count == 0
    assert events == [first, second, third]


def test_load_events_for_run_filters_results_and_keeps_bad_line_count(
    tmp_path: Path,
) -> None:
    """Run-specific loader should filter events while preserving malformed-line count."""
    event_path = tmp_path / "mixed.jsonl"
    event_path.write_text(
        "\n".join(
            [
                '{"event_type":"A","run_id":"r1","payload":{"k":1},"timestamp":"2026-04-05T10:00:00+00:00"}',
                '{"event_type":"B","run_id":"r2","payload":{"k":2},"timestamp":"2026-04-05T10:00:01+00:00"}',
                '{"event_type":"C","run_id":"r1","payload":{"k":3},"timestamp":"2026-04-05T10:00:02+00:00"}',
                '{"event_type":"BROKEN","run_id":"r1","payload":{"k":4},"timestamp":"2026-04-05T10:00:03+00:00"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    events, bad_line_count = load_events_for_run(event_path, "r1")
    assert [event.event_type for event in events] == ["A", "C"]
    assert bad_line_count == 1
