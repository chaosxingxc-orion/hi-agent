"""Unit tests for runtime config management helpers."""

from __future__ import annotations

import pytest
from hi_agent.management.config_history import ConfigHistory
from hi_agent.management.runtime_config import RuntimeConfigStore, patch_runtime_config


def test_runtime_config_patch_bumps_version_and_updates_snapshot() -> None:
    """Patch should increment version and update snapshot values."""
    ticks = iter([100.0, 101.0, 102.0]).__next__
    store = RuntimeConfigStore(
        initial_config={"max_retries": 1},
        now_fn=ticks,
        initial_version=3,
    )
    history = ConfigHistory()

    snapshot = patch_runtime_config(
        store=store,
        history=history,
        patch_data={"max_retries": 2, "timeout_seconds": 10},
        actor="ops-user",
    )

    assert snapshot.version == 4
    assert snapshot.updated_at == 101.0
    assert snapshot.actor == "ops-user"
    assert snapshot.config["max_retries"] == 2
    assert snapshot.config["timeout_seconds"] == 10

    entries = history.list_entries()
    assert len(entries) == 1
    assert entries[0].version == 4
    assert entries[0].changes == {"max_retries": 2, "timeout_seconds": 10}
    assert entries[0].snapshot == snapshot.config


@pytest.mark.parametrize(
    ("patch_data", "actor"),
    [
        ({}, "ops"),
        ({"": 1}, "ops"),
        ({"  ": 1}, "ops"),
        ({1: "bad_key"}, "ops"),  # type: ignore[dict-item]  expiry_wave: Wave 30
        ({"k": "v"}, ""),
        ({"k": "v"}, "   "),
    ],
)
def test_runtime_config_patch_validation_errors(
    patch_data: dict[object, object], actor: str
) -> None:
    """Invalid patch/actor inputs should raise ValueError."""
    store = RuntimeConfigStore(initial_config={"x": 1}, now_fn=lambda: 1.0)
    history = ConfigHistory()

    with pytest.raises(ValueError):
        patch_runtime_config(
            store=store,
            history=history,
            patch_data=patch_data,
            actor=actor,
        )


def test_config_history_list_entries_returns_deterministic_order() -> None:
    """History list should remain deterministic by version then timestamp."""
    ticks = iter([10.0, 20.0, 30.0]).__next__
    store = RuntimeConfigStore(initial_config={"a": 1}, now_fn=ticks, initial_version=1)
    history = ConfigHistory()

    patch_runtime_config(
        store=store,
        history=history,
        patch_data={"a": 2},
        actor="alice",
    )
    patch_runtime_config(
        store=store,
        history=history,
        patch_data={"b": 3},
        actor="bob",
    )

    entries = history.list_entries()
    assert [entry.version for entry in entries] == [2, 3]
    assert [entry.actor for entry in entries] == ["alice", "bob"]
    assert [entry.patched_at for entry in entries] == [20.0, 30.0]
