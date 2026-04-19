"""Unit tests for I-6: ShortTermMemoryStore._memory_path slash sanitisation.

Verifies that reflection session IDs containing '/' are stored as flat JSON
files instead of triggering FileNotFoundError from os.replace().
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hi_agent.memory.short_term import ShortTermMemory, ShortTermMemoryStore


def _make_memory(session_id: str, run_id: str = "run1") -> ShortTermMemory:
    return ShortTermMemory(
        session_id=session_id,
        run_id=run_id,
        task_goal="test goal",
        created_at=datetime.now(UTC).isoformat(),
    )


def test_save_load_with_slash_session_id(tmp_path: Path) -> None:
    """Round-trip save/load with a slash-containing session_id must not raise."""
    store = ShortTermMemoryStore(storage_dir=str(tmp_path), max_sessions=0)
    session_id = "abc/reflect/S1/1"
    mem = _make_memory(session_id)

    store.save(mem)
    loaded = store.load(session_id)

    assert loaded is not None, "load() returned None — file was not written or found"
    assert loaded.session_id == session_id
    assert loaded.task_goal == "test goal"


def test_save_does_not_create_subdirectory(tmp_path: Path) -> None:
    """Saving with a slash session_id must produce a flat file, not nested dirs."""
    store = ShortTermMemoryStore(storage_dir=str(tmp_path), max_sessions=0)
    session_id = "abc/reflect/S1/1"
    store.save(_make_memory(session_id))

    # No subdirectory named "abc" should exist inside tmp_path
    assert not (tmp_path / "abc").exists(), (
        "Subdirectory 'abc' was created — session_id slash was not sanitised"
    )

    # Exactly one .json data file must exist at the flat level
    json_files = [f for f in tmp_path.glob("*.json") if f.name != "_manifest.json"]
    assert len(json_files) == 1, f"Expected 1 flat .json file, got {json_files}"
    assert json_files[0].name == "abc__reflect__S1__1.json"


def test_evict_finds_reflection_memories(tmp_path: Path) -> None:
    """_evict_oldest must discover slash-based session files via glob('*.json')."""
    # Disable auto-eviction during save so we can trigger it manually.
    store = ShortTermMemoryStore(storage_dir=str(tmp_path), max_sessions=0)

    slash_ids = [
        "run1/reflect/s1/1",
        "run1/reflect/s1/2",
        "run1/reflect/s2/1",
        "run1/reflect/s2/2",
    ]
    for sid in slash_ids:
        store.save(_make_memory(sid))

    data_files = [f for f in tmp_path.glob("*.json") if f.name != "_manifest.json"]
    assert len(data_files) == 4, "Pre-condition: 4 data files expected"

    deleted = store._evict_oldest(keep=2)

    remaining = [f for f in tmp_path.glob("*.json") if f.name != "_manifest.json"]
    assert len(remaining) == 2, (
        f"Expected 2 files after eviction, got {len(remaining)}: {remaining}"
    )
    assert deleted == 2
