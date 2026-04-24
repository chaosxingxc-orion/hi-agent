"""Unit tests for L0 JSONL file persistence in RawMemoryStore."""

from __future__ import annotations

import json
from pathlib import Path

from hi_agent.memory.l0_raw import RawEventRecord, RawMemoryStore


def test_append_writes_jsonl_line(tmp_path: Path) -> None:
    """Each appended record produces exactly one valid JSONL line."""
    store = RawMemoryStore(run_id="run-001", base_dir=tmp_path)
    record = RawEventRecord(event_type="StageOpened", payload={"stage_id": "S1"})
    store.append(record)
    store.flush()

    log_file = tmp_path / "logs" / "memory" / "L0" / "run-001.jsonl"
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["run_id"] == "run-001"
    assert data["content"] == {"stage_id": "S1"}
    assert data["metadata"]["event_type"] == "StageOpened"
    assert "timestamp" in data


def test_multiple_appends_produce_multiple_lines(tmp_path: Path) -> None:
    """Multiple appends each produce one JSONL line."""
    store = RawMemoryStore(run_id="run-002", base_dir=tmp_path)
    for i in range(3):
        store.append(RawEventRecord(event_type="Tick", payload={"i": i}))
    store.flush()

    log_file = tmp_path / "logs" / "memory" / "L0" / "run-002.jsonl"
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for idx, line in enumerate(lines):
        data = json.loads(line)
        assert data["content"]["i"] == idx


def test_file_created_at_correct_path(tmp_path: Path) -> None:
    """JSONL file is created at {base_dir}/logs/memory/L0/{run_id}.jsonl."""
    store = RawMemoryStore(run_id="run-abc", base_dir=tmp_path)
    store.append(RawEventRecord(event_type="X", payload={}))
    store.flush()

    expected = tmp_path / "logs" / "memory" / "L0" / "run-abc.jsonl"
    assert expected.exists()


def test_in_memory_behavior_unchanged_without_path() -> None:
    """When run_id/base_dir are omitted, in-memory behavior works normally."""
    store = RawMemoryStore()
    record = RawEventRecord(event_type="StageOpened", payload={"stage_id": "S2"})
    store.append(record)

    assert len(store.list_all()) == 1
    assert store.list_all()[0].event_type == "StageOpened"
    # flush is a no-op — must not raise
    store.flush()


def test_in_memory_records_also_populated_with_persistence(tmp_path: Path) -> None:
    """With file persistence enabled, in-memory records are still populated."""
    store = RawMemoryStore(run_id="run-003", base_dir=tmp_path)
    store.append(RawEventRecord(event_type="Done", payload={"ok": True}))

    records = store.list_all()
    assert len(records) == 1
    assert records[0].event_type == "Done"
