"""Integration test for runtime config command workflow."""

from __future__ import annotations

import pytest
from hi_agent.management.config_history import ConfigHistory
from hi_agent.management.runtime_config import RuntimeConfigStore
from hi_agent.management.runtime_config_commands import (
    cmd_runtime_config_get,
    cmd_runtime_config_history,
    cmd_runtime_config_patch,
)


def test_runtime_config_commands_end_to_end() -> None:
    """Get -> patch -> history should provide a consistent command chain."""
    clock = iter([10.0, 20.0, 30.0]).__next__
    store = RuntimeConfigStore(initial_config={"max_retries": 1}, now_fn=clock)
    history = ConfigHistory()

    before = cmd_runtime_config_get(store)
    patched = cmd_runtime_config_patch(
        store=store,
        history=history,
        patch_data={"max_retries": 2},
        actor="ops",
    )
    entries = cmd_runtime_config_history(history, limit=10)

    assert before["version"] == 0
    assert patched["version"] == 1
    assert entries["count"] == 1
    assert entries["entries"][0]["changes"] == {"max_retries": 2}


def test_runtime_config_commands_history_limit_and_validation() -> None:
    """History limit should work and invalid command inputs should fail."""
    clock = iter([10.0, 20.0, 30.0, 40.0]).__next__
    store = RuntimeConfigStore(initial_config={"timeout": 5}, now_fn=clock)
    history = ConfigHistory()

    cmd_runtime_config_patch(
        store=store,
        history=history,
        patch_data={"timeout": 10},
        actor="ops-a",
    )
    cmd_runtime_config_patch(
        store=store,
        history=history,
        patch_data={"timeout": 15},
        actor="ops-b",
    )

    limited = cmd_runtime_config_history(history, limit=1)
    assert limited["count"] == 1
    assert limited["entries"][0]["actor"] == "ops-b"

    with pytest.raises(ValueError):
        cmd_runtime_config_history(history, limit=0)

    with pytest.raises(ValueError):
        cmd_runtime_config_patch(
            store=store,
            history=history,
            patch_data={"timeout": 20},
            actor=" ",
        )
