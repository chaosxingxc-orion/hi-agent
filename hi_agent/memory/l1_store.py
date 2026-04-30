"""SQLite-backed durable persistence for L1 compressed stage memory.

Stores :class:`~hi_agent.memory.l1_compressed.CompressedStageMemory` records
keyed by ``(tenant_id, run_id, stage_id)``. Survives process restart so a
resumed run can rehydrate prior stage summaries.

Closes RIA A-07. Pattern mirrors
:mod:`hi_agent.memory.sqlite_kg_backend` (SQLite + WAL + ``threading.Lock``).

Rule 5 — sync interface; no async resource constructed in __init__.
Rule 6 — single construction path (DI from builder); ``db_path`` required.
Rule 11 — durable under research/prod (caller picks db_path); in-memory
under dev (caller passes ``:memory:`` or skips wiring entirely).
Rule 12 — every row carries ``tenant_id``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from hi_agent.memory.l1_compressed import CompressedStageMemory


class L1CompressedMemoryStore:
    """Durable store for ``CompressedStageMemory`` records.

    Schema::

        CREATE TABLE l1_compressed_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            run_id    TEXT NOT NULL,
            stage_id  TEXT NOT NULL,
            compressed_blob BLOB,
            created_at REAL
        )

    Index on ``(tenant_id, run_id)`` for query()'s lookup path.

    Args:
        db_path: Filesystem path to the SQLite database. Pass ``":memory:"``
            for an ephemeral in-memory store (tests / dev only).

    Thread-safe for concurrent in-process access via ``threading.Lock``.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS l1_compressed_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        stage_id TEXT NOT NULL,
        compressed_blob BLOB,
        created_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_l1_tenant_run
        ON l1_compressed_memory (tenant_id, run_id);
    """

    def __init__(self, db_path: str | Path) -> None:
        if db_path is None or str(db_path) == "":
            raise ValueError(
                "L1CompressedMemoryStore requires a non-empty db_path; "
                "pass ':memory:' for an in-memory store (Rule 6)."
            )
        path_str = str(db_path)
        if path_str != ":memory:":
            Path(path_str).parent.mkdir(parents=True, exist_ok=True)
        self._path = path_str
        self._lock = threading.Lock()
        self._con = sqlite3.connect(path_str, check_same_thread=False)
        if path_str != ":memory:":
            self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.executescript(self._DDL)
        self._con.commit()

    def register(
        self,
        tenant_id: str,
        run_id: str,
        stage_id: str,
        memory: CompressedStageMemory | dict[str, Any] | bytes,
    ) -> int:
        """Persist one compressed stage record.

        Args:
            tenant_id: Tenant scope (required, Rule 12).
            run_id: Owning run identifier.
            stage_id: Stage identifier within the run.
            memory: Either a :class:`CompressedStageMemory`, a dict, or raw
                bytes. Dataclasses and dicts are JSON-encoded; bytes are
                stored as-is.

        Returns:
            The auto-generated row id.
        """
        if not tenant_id:
            raise ValueError("L1CompressedMemoryStore.register requires tenant_id (Rule 12).")
        if not run_id:
            raise ValueError("L1CompressedMemoryStore.register requires run_id.")
        if not stage_id:
            raise ValueError("L1CompressedMemoryStore.register requires stage_id.")

        blob = self._encode(memory)
        with self._lock:
            cur = self._con.execute(
                """
                INSERT INTO l1_compressed_memory
                    (tenant_id, run_id, stage_id, compressed_blob, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tenant_id, run_id, stage_id, blob, time.time()),
            )
            self._con.commit()
            return int(cur.lastrowid or 0)

    def query(self, tenant_id: str, run_id: str) -> list[CompressedStageMemory]:
        """Return all CompressedStageMemory records for a (tenant, run).

        Records are returned in insertion order (id ASC).

        Returns an empty list when no rows match.
        """
        with self._lock:
            rows = self._con.execute(
                """
                SELECT compressed_blob FROM l1_compressed_memory
                WHERE tenant_id = ? AND run_id = ?
                ORDER BY id ASC
                """,
                (tenant_id, run_id),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode(memory: CompressedStageMemory | dict[str, Any] | bytes) -> bytes:
        if isinstance(memory, bytes):
            return memory
        if isinstance(memory, CompressedStageMemory):
            payload = {
                "stage_id": memory.stage_id,
                "tenant_id": memory.tenant_id,
                "findings": list(memory.findings),
                "decisions": list(memory.decisions),
                "outcome": memory.outcome,
                "contradiction_refs": list(memory.contradiction_refs),
                "key_entities": list(memory.key_entities),
                "source_evidence_count": memory.source_evidence_count,
                "compression_method": memory.compression_method,
            }
        elif isinstance(memory, dict):
            payload = memory
        else:
            raise TypeError(
                f"L1CompressedMemoryStore: unsupported memory type {type(memory).__name__}"
            )
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _decode(blob: bytes | None) -> CompressedStageMemory:
        if not blob:
            return CompressedStageMemory(stage_id="")
        data = json.loads(bytes(blob).decode("utf-8"))
        method = data.get("compression_method", "direct")
        if method not in ("direct", "llm", "fallback"):
            method = "direct"
        return CompressedStageMemory(
            stage_id=data.get("stage_id", ""),
            tenant_id=data.get("tenant_id", ""),
            findings=list(data.get("findings", [])),
            decisions=list(data.get("decisions", [])),
            outcome=data.get("outcome", "active"),
            contradiction_refs=list(data.get("contradiction_refs", [])),
            key_entities=list(data.get("key_entities", [])),
            source_evidence_count=int(data.get("source_evidence_count", 0)),
            compression_method=method,
        )
