"""Unit tests for operational snapshot store."""

from __future__ import annotations

import pytest
from hi_agent.management.ops_snapshot_store import OpsSnapshotStore


def test_append_and_latest_and_list_run_are_deterministic() -> None:
    """Store should append snapshots and return deterministic latest/list outputs."""
    store = OpsSnapshotStore()
    store.append({"run_id": "run-1", "timestamp": 10.0, "status": "ok"})
    store.append({"run_id": "run-2", "timestamp": 20.0, "status": "warn"})
    store.append({"run_id": "run-1", "timestamp": 30.0, "status": "error"})

    latest = store.latest("run-1")
    assert latest is not None
    assert latest["timestamp"] == 30.0
    assert latest["status"] == "error"

    run_entries = store.list_run("run-1")
    assert [entry["timestamp"] for entry in run_entries] == [10.0, 30.0]


def test_list_all_supports_limit_and_descending_order() -> None:
    """list_all should return newest snapshots first and honor limit."""
    store = OpsSnapshotStore()
    store.append({"run_id": "run-1", "timestamp": 10.0})
    store.append({"run_id": "run-2", "timestamp": 30.0})
    store.append({"run_id": "run-3", "timestamp": 20.0})

    all_entries = store.list_all()
    assert [entry["run_id"] for entry in all_entries] == ["run-2", "run-3", "run-1"]

    limited = store.list_all(limit=2)
    assert [entry["run_id"] for entry in limited] == ["run-2", "run-3"]


def test_store_is_copy_safe_for_append_and_reads() -> None:
    """External mutations should not affect stored snapshot state."""
    store = OpsSnapshotStore()
    payload = {"run_id": "run-copy", "timestamp": 1.0, "meta": {"a": 1}}
    stored = store.append(payload)
    payload["meta"]["a"] = 999
    stored["meta"]["a"] = 888

    latest = store.latest("run-copy")
    assert latest is not None
    assert latest["meta"]["a"] == 1


@pytest.mark.parametrize(
    ("run_id", "timestamp"),
    [
        ("", 1.0),
        ("   ", 1.0),
        ("run-1", "bad"),
    ],
)
def test_append_validation_errors(run_id: str, timestamp: object) -> None:
    """Invalid snapshot payload should raise ValueError."""
    store = OpsSnapshotStore()
    with pytest.raises(ValueError):
        store.append({"run_id": run_id, "timestamp": timestamp})


def test_list_all_limit_validation() -> None:
    """Non-positive limit should be rejected."""
    store = OpsSnapshotStore()
    with pytest.raises(ValueError):
        store.list_all(limit=0)
