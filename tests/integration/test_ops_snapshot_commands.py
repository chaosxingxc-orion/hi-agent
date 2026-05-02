"""Unit tests for ops snapshot command wrappers."""

from __future__ import annotations

import pytest
from hi_agent.management.ops_snapshot_commands import (
    cmd_ops_snapshot_latest,
    cmd_ops_snapshot_list,
    cmd_ops_snapshot_put,
)
from hi_agent.management.ops_snapshot_store import OpsSnapshotStore


def test_ops_snapshot_commands_roundtrip() -> None:
    """Put/latest/list should return normalized payloads."""
    store = OpsSnapshotStore()
    cmd_ops_snapshot_put(store, {"run_id": "run-1", "timestamp": 1.0, "status": "ok"})
    cmd_ops_snapshot_put(store, {"run_id": "run-1", "timestamp": 2.0, "status": "degraded"})

    latest = cmd_ops_snapshot_latest(store, "run-1")
    listed = cmd_ops_snapshot_list(store, "run-1")

    assert latest["found"] is True
    assert latest["snapshot"]["timestamp"] == 2.0
    assert listed["count"] == 2


def test_ops_snapshot_commands_validate_store_type() -> None:
    """All snapshot commands should reject invalid store objects."""
    with pytest.raises(TypeError, match="store must be an OpsSnapshotStore"):
        cmd_ops_snapshot_put(object(), {"run_id": "run-1", "timestamp": 1.0})  # type: ignore[arg-type]  expiry_wave: Wave 30
    with pytest.raises(TypeError, match="store must be an OpsSnapshotStore"):
        cmd_ops_snapshot_latest(object(), "run-1")  # type: ignore[arg-type]  expiry_wave: Wave 30
    with pytest.raises(TypeError, match="store must be an OpsSnapshotStore"):
        cmd_ops_snapshot_list(object(), "run-1")  # type: ignore[arg-type]  expiry_wave: Wave 30
