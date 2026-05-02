"""Consistency compensation journals for local-success/backend-failure writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ConsistencyIssue:
    """Represents a write that succeeded locally but failed in backend.

    Attributes:
      operation: Name of the local mutation that needs compensation.
      context: Serializable payload needed to replay or inspect the mutation.
      error: Original backend failure details.
    """

    operation: str
    context: dict[str, Any]
    error: str


class InMemoryConsistencyJournal:
    """Simple in-memory journal for consistency compensation records."""

    def __init__(self) -> None:
        """Initialize empty issue storage."""
        self._issues: list[ConsistencyIssue] = []

    def append(self, issue: ConsistencyIssue) -> None:
        """Store a consistency issue.

        Args:
          issue: Record to append.
        """
        self._issues.append(issue)

    def list_issues(self) -> list[ConsistencyIssue]:
        """Return a snapshot of recorded issues."""
        return list(self._issues)

    def size(self) -> int:
        """Return the number of recorded issues currently in the journal."""
        return len(self._issues)


class FileBackedConsistencyJournal:
    """Append-only file-backed consistency journal using JSON Lines.

    The journal keeps an in-memory snapshot for cheap reads and persists each
    appended issue as one JSON object per line. During load/reload, malformed
    lines are skipped so a partially corrupted file does not block recovery.
    """

    def __init__(self, file_path: str | Path) -> None:
        """Initialize a durable journal and load existing records.

        Args:
          file_path: Destination JSONL file for durable issue storage.
        """
        self._file_path = Path(file_path)
        self._issues: list[ConsistencyIssue] = []
        self.reload_from_disk()

    def append(self, issue: ConsistencyIssue) -> None:
        """Append an issue to memory and durable storage.

        Args:
          issue: Record to append.
        """
        self._issues.append(issue)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            {
                "operation": issue.operation,
                "context": issue.context,
                "error": issue.error,
            },
            separators=(",", ":"),
        )
        with self._file_path.open("a", encoding="utf-8") as fp:
            fp.write(serialized)
            fp.write("\n")

    def list_issues(self) -> list[ConsistencyIssue]:
        """Return a snapshot of currently loaded issues."""
        return list(self._issues)

    def size(self) -> int:
        """Return the number of loaded issues in the current snapshot."""
        return len(self._issues)

    def reload_from_disk(self) -> None:
        """Reload issue snapshot from disk, skipping malformed records."""
        self._issues = []
        if not self._file_path.exists():
            return

        with self._file_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                issue = self._parse_line(line)
                if issue is not None:
                    self._issues.append(issue)

    @staticmethod
    def _parse_line(line: str) -> ConsistencyIssue | None:
        """Parse one JSONL line into a ``ConsistencyIssue`` when valid.

        Args:
          line: Raw line read from the journal file.

        Returns:
          A parsed ``ConsistencyIssue`` when line is valid, otherwise ``None``.
        """
        stripped = line.strip()
        if not stripped:
            return None

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:  # rule7-exempt: expiry_wave="permanent"
            return None

        if not isinstance(payload, dict):
            return None

        operation = payload.get("operation")
        context = payload.get("context")
        error = payload.get("error")

        if not isinstance(operation, str):
            return None
        if not isinstance(context, dict):
            return None
        if not isinstance(error, str):
            return None

        return ConsistencyIssue(operation=operation, context=context, error=error)
