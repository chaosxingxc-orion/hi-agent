"""Runtime configuration management helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import time

from hi_agent.management.config_history import ConfigHistory, ConfigHistoryEntry


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """Snapshot returned after a runtime config patch."""

    version: int
    config: dict[str, object]
    actor: str
    updated_at: float


class RuntimeConfigStore:
    """Versioned in-memory runtime config store."""

    def __init__(
        self,
        *,
        initial_config: Mapping[str, object] | None = None,
        now_fn: Callable[[], float] | None = None,
        initial_version: int = 0,
        capture_init_timestamp: bool = True,
    ) -> None:
        """Initialize store with optional initial config and version."""
        if initial_version < 0:
            raise ValueError("initial_version must be >= 0")
        self._config: dict[str, object] = dict(initial_config or {})
        self._version = int(initial_version)
        self._now_fn = now_fn or time
        # Capture baseline timestamp optionally; enabled for direct store usage.
        self._updated_at = float(self._now_fn()) if capture_init_timestamp else 0.0

    def snapshot(self) -> dict[str, object]:
        """Return a copy of current config."""
        return dict(self._config)

    def version(self) -> int:
        """Return current config version."""
        return self._version

    def apply_patch(self, patch_data: Mapping[str, object]) -> tuple[int, dict[str, object], float]:
        """Validate and apply one patch, returning new version/snapshot/timestamp."""
        if not patch_data:
            raise ValueError("patch_data must not be empty")
        for key in patch_data:
            if not isinstance(key, str) or not key.strip():
                raise ValueError("all config keys must be non-empty strings")
        self._config.update(dict(patch_data))
        self._version += 1
        self._updated_at = float(self._now_fn())
        return self._version, self.snapshot(), self._updated_at


def patch_runtime_config(
    *,
    store: RuntimeConfigStore,
    history: ConfigHistory,
    patch_data: Mapping[str, object],
    actor: str,
) -> RuntimeConfigSnapshot:
    """Apply a patch and append a matching history entry."""
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("actor must be a non-empty string")

    version, snapshot, changed_at = store.apply_patch(patch_data)
    history.append(
        ConfigHistoryEntry(
            version=version,
            changed_by=normalized_actor,
            changed_at=changed_at,
            patch=dict(patch_data),
            snapshot=dict(snapshot),
        )
    )
    return RuntimeConfigSnapshot(
        version=version,
        config=snapshot,
        actor=normalized_actor,
        updated_at=changed_at,
    )


class RuntimeConfigManager:
    """Compatibility manager preserved for existing tests and call sites."""

    def __init__(
        self,
        *,
        initial: Mapping[str, object] | None = None,
        history: ConfigHistory | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        """Initialize manager with shared implementation primitives."""
        self._history = history or ConfigHistory()
        self._store = RuntimeConfigStore(
            initial_config=initial,
            now_fn=now_fn,
            initial_version=0,
            capture_init_timestamp=False,
        )

    def snapshot(self) -> dict[str, object]:
        """Return current runtime config snapshot."""
        return self._store.snapshot()

    def version(self) -> int:
        """Return current config version."""
        return self._store.version()

    def patch(self, *, changed_by: str, values: Mapping[str, object]) -> ConfigHistoryEntry:
        """Apply one patch and return the created history entry."""
        snapshot = patch_runtime_config(
            store=self._store,
            history=self._history,
            patch_data=values,
            actor=changed_by,
        )
        latest = self._history.latest()
        if latest is None:
            raise RuntimeError("history entry missing after patch")
        if latest.version != snapshot.version:
            raise RuntimeError("history/version mismatch after patch")
        return latest

    def history(self) -> list[ConfigHistoryEntry]:
        """Return configuration history."""
        return self._history.list_entries()
