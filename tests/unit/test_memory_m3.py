"""Tests for M-3: L0Summarizer."""

from __future__ import annotations

import json
from pathlib import Path

from hi_agent.memory.l0_summarizer import L0Summarizer


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts as JSONL lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_m3_summarize_stage_complete_events(tmp_path: Path) -> None:
    """stage_complete events produce tasks_completed and key_learnings entries."""
    run_id = "run-sum-001"
    log_path = tmp_path / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
    records = [
        {
            "timestamp": "2026-04-15T00:00:00+00:00",
            "run_id": run_id,
            "content": {"stage_id": "understand", "result": "analysis done"},
            "metadata": {"event_type": "stage_complete", "tags": []},
        },
        {
            "timestamp": "2026-04-15T00:01:00+00:00",
            "run_id": run_id,
            "content": {"stage_id": "synthesize", "result": "synthesis done"},
            "metadata": {"event_type": "stage_complete", "tags": []},
        },
    ]
    _write_jsonl(log_path, records)

    summary = L0Summarizer().summarize_run(run_id, tmp_path)
    assert summary is not None
    assert "understand" in summary.tasks_completed
    assert "synthesize" in summary.tasks_completed
    assert len(summary.key_learnings) == 2


def test_m3_summarize_pattern_events(tmp_path: Path) -> None:
    """reflection/insight/pattern events populate patterns_observed."""
    run_id = "run-sum-002"
    log_path = tmp_path / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
    records = [
        {
            "timestamp": "2026-04-15T00:00:00+00:00",
            "run_id": run_id,
            "content": {"message": "retries help"},
            "metadata": {"event_type": "reflection", "tags": []},
        },
        {
            "timestamp": "2026-04-15T00:01:00+00:00",
            "run_id": run_id,
            "content": {"message": "caching reduces cost"},
            "metadata": {"event_type": "insight", "tags": []},
        },
    ]
    _write_jsonl(log_path, records)

    summary = L0Summarizer().summarize_run(run_id, tmp_path)
    assert summary is not None
    assert len(summary.patterns_observed) == 2


def test_m3_empty_file_returns_none(tmp_path: Path) -> None:
    """An empty JSONL file returns None."""
    run_id = "run-empty"
    log_path = tmp_path / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    result = L0Summarizer().summarize_run(run_id, tmp_path)
    assert result is None


def test_m3_nonexistent_file_returns_none(tmp_path: Path) -> None:
    """A missing JSONL file returns None."""
    result = L0Summarizer().summarize_run("no-such-run", tmp_path)
    assert result is None
