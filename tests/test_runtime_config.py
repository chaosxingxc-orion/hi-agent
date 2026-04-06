"""Unit tests for runtime configuration manager."""

from __future__ import annotations

import pytest
from hi_agent.management.runtime_config import RuntimeConfigManager


def test_runtime_config_patch_updates_version_and_snapshot() -> None:
    """Patch should increment version and update current snapshot."""
    manager = RuntimeConfigManager(initial={"a": 1}, now_fn=lambda: 50.0)
    entry = manager.patch(changed_by="ops", values={"a": 2, "b": True})
    assert entry.version == 1
    assert manager.version() == 1
    assert manager.snapshot() == {"a": 2, "b": True}
    assert entry.changed_at == 50.0


def test_runtime_config_history_records_multiple_changes() -> None:
    """History should preserve each patch with monotonically increasing version."""
    timestamps = iter([10.0, 20.0]).__next__
    manager = RuntimeConfigManager(now_fn=timestamps)
    manager.patch(changed_by="ops", values={"x": 1})
    manager.patch(changed_by="ops", values={"x": 2})
    versions = [entry.version for entry in manager.history()]
    assert versions == [1, 2]


def test_runtime_config_rejects_empty_actor_or_patch() -> None:
    """Manager should reject invalid actor or empty patch input."""
    manager = RuntimeConfigManager()
    with pytest.raises(ValueError):
        manager.patch(changed_by="", values={"x": 1})
    with pytest.raises(ValueError):
        manager.patch(changed_by="ops", values={})

