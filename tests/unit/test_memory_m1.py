"""Tests for M-1: RawMemoryStore close() + context manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hi_agent.memory.l0_raw import RawEventRecord, RawMemoryStore


def test_m1_close_closes_file_handle(tmp_path: Path) -> None:
    """close() flushes and closes the underlying file handle."""
    store = RawMemoryStore(run_id="run-close", base_dir=tmp_path)
    assert store._file is not None
    store.close()
    assert store._file is None


def test_m1_close_is_idempotent(tmp_path: Path) -> None:
    """Calling close() twice must not raise."""
    store = RawMemoryStore(run_id="run-idem", base_dir=tmp_path)
    store.close()
    store.close()  # second call — must not raise


def test_m1_append_after_close_raises(tmp_path: Path) -> None:
    """append() after close() raises ValueError when a run_id was given."""
    store = RawMemoryStore(run_id="run-closed", base_dir=tmp_path)
    store.close()
    with pytest.raises(ValueError, match="closed"):
        store.append(RawEventRecord(event_type="X", payload={}))


def test_m1_append_on_in_memory_store_never_raises() -> None:
    """append() on a store without run_id never raises (no file to close)."""
    store = RawMemoryStore()
    store.close()  # no-op
    # Must NOT raise — no run_id means the closed check is not triggered
    store.append(RawEventRecord(event_type="X", payload={}))


def test_m1_context_manager(tmp_path: Path) -> None:
    """Context manager closes the store on exit."""
    with RawMemoryStore(run_id="run-ctx", base_dir=tmp_path) as store:
        store.append(RawEventRecord(event_type="Y", payload={"k": 1}))
    # After exiting the context, the file handle should be closed
    assert store._file is None
    # JSONL file must exist with the written record
    log_file = tmp_path / "logs" / "memory" / "L0" / "run-ctx.jsonl"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["metadata"]["event_type"] == "Y"
