"""Evidence collection and storage for Harness actions."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

from hi_agent.harness.contracts import EvidenceRecord


@runtime_checkable
class EvidenceStoreProtocol(Protocol):
    """Common interface for evidence stores."""

    def store(self, record: EvidenceRecord) -> str: ...
    def get(self, evidence_ref: str) -> EvidenceRecord | None: ...
    def get_by_action(self, action_id: str) -> list[EvidenceRecord]: ...
    def count(self) -> int: ...


class EvidenceStore:
    """In-memory evidence store with ref-based retrieval.

    Stores evidence records keyed by evidence_ref, with secondary
    indexing by action_id for efficient per-action lookups.
    """

    def __init__(self) -> None:
        """Initialize empty evidence store."""
        self._records: dict[str, EvidenceRecord] = {}
        self._by_action: dict[str, list[str]] = {}

    def store(self, record: EvidenceRecord) -> str:
        """Store an evidence record.

        Args:
            record: The evidence record to store.

        Returns:
            The evidence_ref of the stored record.

        Raises:
            ValueError: If evidence_ref is empty.
        """
        if not record.evidence_ref:
            raise ValueError("evidence_ref must not be empty")
        self._records[record.evidence_ref] = record
        self._by_action.setdefault(record.action_id, []).append(
            record.evidence_ref
        )
        return record.evidence_ref

    def get(self, evidence_ref: str) -> EvidenceRecord | None:
        """Retrieve a single evidence record by ref.

        Args:
            evidence_ref: The unique evidence reference.

        Returns:
            The evidence record, or None if not found.
        """
        return self._records.get(evidence_ref)

    def get_by_action(self, action_id: str) -> list[EvidenceRecord]:
        """Retrieve all evidence records for an action.

        Args:
            action_id: The action identifier.

        Returns:
            List of evidence records, possibly empty.
        """
        refs = self._by_action.get(action_id, [])
        return [self._records[r] for r in refs if r in self._records]

    def count(self) -> int:
        """Return total number of stored evidence records."""
        return len(self._records)

    def get_all(self) -> list[EvidenceRecord]:
        """Return all stored evidence records."""
        return list(self._records.values())


class SqliteEvidenceStore:
    """SQLite-backed evidence store for durable audit trails.

    Persists evidence records to a SQLite database so they survive
    process restarts.  Thread-safe via ``check_same_thread=False``.
    """

    _CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS evidence (
    evidence_ref  TEXT PRIMARY KEY,
    action_id     TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    content       TEXT NOT NULL,
    timestamp     TEXT NOT NULL
)
"""
    _CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_evidence_action_id
ON evidence (action_id)
"""

    def __init__(self, db_path: str | Path = ".hi_agent/evidence.db") -> None:
        """Open (or create) the evidence database.

        Args:
            db_path: Filesystem path for the SQLite file.  Parent
                directories are created automatically.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.execute(self._CREATE_INDEX)
        self._conn.commit()

    # -- write -----------------------------------------------------------

    def store(self, record: EvidenceRecord) -> str:
        """Persist an evidence record (INSERT OR REPLACE).

        Args:
            record: The evidence record to store.

        Returns:
            The evidence_ref of the stored record.

        Raises:
            ValueError: If evidence_ref is empty.
        """
        if not record.evidence_ref:
            raise ValueError("evidence_ref must not be empty")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO evidence "
                "(evidence_ref, action_id, evidence_type, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.evidence_ref,
                    record.action_id,
                    record.evidence_type,
                    json.dumps(record.content),
                    record.timestamp,
                ),
            )
            self._conn.commit()
        return record.evidence_ref

    def store_many(self, events: list[EvidenceRecord]) -> None:
        """Write a batch of evidence records in a single transaction.

        All records are committed atomically.  If any INSERT fails the
        entire batch is rolled back.

        Args:
            events: Evidence records to persist.

        Raises:
            ValueError: If any record has an empty evidence_ref.
        """
        for record in events:
            if not record.evidence_ref:
                raise ValueError("evidence_ref must not be empty")
        with self._lock:
            try:
                for record in events:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO evidence "
                        "(evidence_ref, action_id, evidence_type, content, timestamp) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            record.evidence_ref,
                            record.action_id,
                            record.evidence_type,
                            json.dumps(record.content),
                            record.timestamp,
                        ),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Explicit transaction context; caller controls commit timing.

        Yields the raw ``sqlite3.Connection`` so the caller can issue
        arbitrary SQL within a single transaction.  Commits on clean
        exit, rolls back on exception.

        Example::

            with store.transaction() as conn:
                conn.execute("INSERT OR REPLACE INTO evidence ...")
        """
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # -- read ------------------------------------------------------------

    def _row_to_record(self, row: tuple) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_ref=row[0],
            action_id=row[1],
            evidence_type=row[2],
            content=json.loads(row[3]),
            timestamp=row[4],
        )

    def get(self, evidence_ref: str) -> EvidenceRecord | None:
        """Retrieve a single evidence record by ref."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT evidence_ref, action_id, evidence_type, content, timestamp "
                "FROM evidence WHERE evidence_ref = ?",
                (evidence_ref,),
            )
            row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def get_by_action(self, action_id: str) -> list[EvidenceRecord]:
        """Retrieve all evidence records for an action."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT evidence_ref, action_id, evidence_type, content, timestamp "
                "FROM evidence WHERE action_id = ?",
                (action_id,),
            )
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_all(self) -> list[EvidenceRecord]:
        """Return all stored evidence records."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT evidence_ref, action_id, evidence_type, content, timestamp "
                "FROM evidence",
            )
            rows = cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def count(self) -> int:
        """Return total number of stored evidence records."""
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM evidence")
            return cur.fetchone()[0]

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
