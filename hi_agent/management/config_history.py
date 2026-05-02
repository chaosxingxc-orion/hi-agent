"""Versioned runtime configuration history."""

from __future__ import annotations

from dataclasses import dataclass


# W31 T-24' decision: in-process config snapshot; tenant-agnostic.
# scope: process-internal
@dataclass(frozen=True)
class ConfigHistoryEntry:
    """A single immutable runtime config change entry."""

    version: int
    changed_by: str
    changed_at: float
    patch: dict[str, object]
    snapshot: dict[str, object]

    @property
    def actor(self) -> str:
        """Compatibility alias for changed_by."""
        return self.changed_by

    @property
    def patched_at(self) -> float:
        """Compatibility alias for changed_at."""
        return self.changed_at

    @property
    def changes(self) -> dict[str, object]:
        """Compatibility alias for patch."""
        return self.patch


class ConfigHistory:
    """In-memory append-only history for runtime configuration changes."""

    def __init__(self) -> None:
        """Initialize an empty change history."""
        self._entries: list[ConfigHistoryEntry] = []

    def append(self, entry: ConfigHistoryEntry) -> None:
        """Append one change record to history."""
        self._entries.append(entry)

    def list_entries(self) -> list[ConfigHistoryEntry]:
        """Return history entries in insertion order."""
        return list(self._entries)

    def latest(self) -> ConfigHistoryEntry | None:
        """Return most recent history entry."""
        return self._entries[-1] if self._entries else None
