"""Tests for runtime config command helpers."""

from __future__ import annotations

from hi_agent.management.config_history import ConfigHistory
from hi_agent.management.runtime_config import RuntimeConfigStore
from hi_agent.management.runtime_config_commands import (
    cmd_runtime_config_get,
    cmd_runtime_config_history,
    cmd_runtime_config_patch,
)


def test_cmd_runtime_config_get_returns_snapshot_payload() -> None:
    """Get command should expose command name, version, and config."""
    store = RuntimeConfigStore(initial_config={"a": 1}, now_fn=lambda: 10.0)
    payload = cmd_runtime_config_get(store)
    assert payload["command"] == "runtime_config_get"
    assert payload["version"] == 0
    assert payload["config"] == {"a": 1}


def test_cmd_runtime_config_patch_updates_store_and_history() -> None:
    """Patch command should return new snapshot and write history."""
    ticks = iter([10.0, 20.0, 30.0]).__next__
    store = RuntimeConfigStore(initial_config={"max_retries": 1}, now_fn=ticks)
    history = ConfigHistory()

    payload = cmd_runtime_config_patch(
        store=store,
        history=history,
        patch_data={"max_retries": 2},
        actor="ops",
    )

    assert payload["command"] == "runtime_config_patch"
    assert payload["version"] == 1
    assert payload["actor"] == "ops"
    assert payload["config"]["max_retries"] == 2

    history_payload = cmd_runtime_config_history(history)
    assert history_payload["count"] == 1
    assert history_payload["entries"][0]["changes"] == {"max_retries": 2}


def test_cmd_runtime_config_history_returns_empty_entries_when_no_data() -> None:
    """History command should be stable when history is empty."""
    payload = cmd_runtime_config_history(ConfigHistory())
    assert payload == {
        "command": "runtime_config_history",
        "count": 0,
        "entries": [],
    }
