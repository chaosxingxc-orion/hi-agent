"""Command-style helpers for runtime configuration management."""

from __future__ import annotations

from hi_agent.management.config_history import ConfigHistory
from hi_agent.management.runtime_config import RuntimeConfigStore, patch_runtime_config


def cmd_runtime_config_get(store: RuntimeConfigStore) -> dict[str, object]:
    """Return current runtime config snapshot payload."""
    return {
        "command": "runtime_config_get",
        "version": store.version(),
        "config": store.snapshot(),
    }


def cmd_runtime_config_patch(
    *,
    store: RuntimeConfigStore,
    history: ConfigHistory,
    patch_data: dict[str, object],
    actor: str,
) -> dict[str, object]:
    """Apply runtime config patch and return command-style response."""
    snapshot = patch_runtime_config(
        store=store,
        history=history,
        patch_data=patch_data,
        actor=actor,
    )
    return {
        "command": "runtime_config_patch",
        "version": snapshot.version,
        "actor": snapshot.actor,
        "updated_at": snapshot.updated_at,
        "config": snapshot.config,
    }


def cmd_runtime_config_history(
    history: ConfigHistory,
    limit: int | None = None,
) -> dict[str, object]:
    """Return runtime config history entries with optional result limit."""
    if limit is not None and limit <= 0:
        raise ValueError("limit must be > 0 when provided")
    rows: list[dict[str, object]] = []
    for entry in history.list_entries():
        rows.append(
            {
                "version": entry.version,
                "actor": entry.actor,
                "patched_at": entry.patched_at,
                "changes": dict(entry.changes),
                "snapshot": dict(entry.snapshot),
            }
        )
    if limit is not None:
        rows = rows[-limit:]
    return {
        "command": "runtime_config_history",
        "count": len(rows),
        "entries": rows,
    }
