"""SQLite-backed durable persistence for the L2 run-memory index.

Stores one :class:`~hi_agent.memory.l2_index.RunMemoryIndex` per
``(tenant_id, run_id)`` so a resumed run can recover its compact navigation
index plus optional embedding vectors and summary text. Closes RIA A-07.

Pattern mirrors :mod:`hi_agent.memory.sqlite_kg_backend` (SQLite + WAL +
``threading.Lock``).

Rule 5 — sync interface; no async resource constructed in __init__.
Rule 6 — single construction path (DI from builder); ``db_path`` required.
Rule 11 — durable under research/prod (caller picks db_path); in-memory
under dev (caller passes ``:memory:`` or skips wiring entirely).
Rule 12 — every row carries ``tenant_id``.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any

from hi_agent.memory.l2_index import RunMemoryIndex, StagePointer
from hi_agent.observability.silent_degradation import record_silent_degradation


class L2RunMemoryIndexStore:
    """Durable store for ``RunMemoryIndex`` records.

    Schema::

        CREATE TABLE l2_run_memory_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            embedding_vector BLOB,
            summary_text TEXT,
            created_at REAL
        )

    Index on ``(tenant_id, run_id)`` for query()'s lookup path.

    The latest row per ``(tenant_id, run_id)`` is the authoritative index.

    Args:
        db_path: Filesystem path to the SQLite database. Pass ``":memory:"``
            for an ephemeral in-memory store (tests / dev only).

    Thread-safe for concurrent in-process access via ``threading.Lock``.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS l2_run_memory_index (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        embedding_vector BLOB,
        summary_text TEXT,
        created_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_l2_tenant_run
        ON l2_run_memory_index (tenant_id, run_id);
    """

    def __init__(self, db_path: str | Path) -> None:
        if db_path is None or str(db_path) == "":
            raise ValueError(
                "L2RunMemoryIndexStore requires a non-empty db_path; "
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
        index: RunMemoryIndex | dict[str, Any],
        embedding: list[float] | bytes | None = None,
        summary_text: str = "",
    ) -> int:
        """Persist one RunMemoryIndex record.

        Each call inserts a new row; ``query()`` returns the latest. This
        keeps writes append-only so concurrent writers never block on row
        upserts.

        Args:
            tenant_id: Tenant scope (required, Rule 12).
            run_id: Owning run identifier.
            index: Either a :class:`RunMemoryIndex` or a dict with
                ``run_id`` / ``stages`` keys.
            embedding: Optional embedding vector (list of floats or raw
                bytes). Stored verbatim when bytes; packed as little-endian
                float64 when a list.
            summary_text: Optional human-readable summary of the run.

        Returns:
            The auto-generated row id.
        """
        if not tenant_id:
            raise ValueError("L2RunMemoryIndexStore.register requires tenant_id (Rule 12).")
        if not run_id:
            raise ValueError("L2RunMemoryIndexStore.register requires run_id.")

        index_blob = self._encode_index(index)
        embed_blob = self._encode_embedding(embedding)
        # Combine the index payload and embedding into one BLOB column so the
        # schema stays simple (the spec calls for a single embedding_vector
        # column). Index payload always present; embedding optional.
        # We pack as: 4-byte big-endian int = index_len, index_bytes, embedding_bytes.
        header = struct.pack(">I", len(index_blob))
        combined = header + index_blob + (embed_blob or b"")

        with self._lock:
            cur = self._con.execute(
                """
                INSERT INTO l2_run_memory_index
                    (tenant_id, run_id, embedding_vector, summary_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tenant_id, run_id, combined, summary_text, time.time()),
            )
            self._con.commit()
            return int(cur.lastrowid or 0)

    def query(self, tenant_id: str, run_id: str) -> RunMemoryIndex | None:
        """Return the latest RunMemoryIndex for a (tenant, run), or None.

        Latest = highest ``id`` row matching the scope.
        """
        with self._lock:
            row = self._con.execute(
                """
                SELECT embedding_vector, summary_text FROM l2_run_memory_index
                WHERE tenant_id = ? AND run_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (tenant_id, run_id),
            ).fetchone()
        if row is None:
            return None
        combined = row[0]
        return self._decode_index(combined)

    def query_summary(self, tenant_id: str, run_id: str) -> str | None:
        """Return the latest summary_text for a (tenant, run), or None."""
        with self._lock:
            row = self._con.execute(
                """
                SELECT summary_text FROM l2_run_memory_index
                WHERE tenant_id = ? AND run_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (tenant_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return row[0] or ""

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_index(index: RunMemoryIndex | dict[str, Any]) -> bytes:
        if isinstance(index, RunMemoryIndex):
            payload = {
                "run_id": index.run_id,
                "stages": [
                    {"stage_id": p.stage_id, "outcome": p.outcome}
                    for p in index.stages
                ],
            }
        elif isinstance(index, dict):
            payload = index
        else:
            raise TypeError(
                f"L2RunMemoryIndexStore: unsupported index type {type(index).__name__}"
            )
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _decode_index(combined: bytes | None) -> RunMemoryIndex | None:
        if not combined or len(combined) < 4:
            return None
        index_len = struct.unpack(">I", bytes(combined[:4]))[0]
        if 4 + index_len > len(combined):
            return None
        index_bytes = bytes(combined[4 : 4 + index_len])
        try:
            data = json.loads(index_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # Corrupt index blob: treat as missing rather than crash.
            record_silent_degradation(
                component="memory.l2_store.L2RunMemoryIndexStore._decode_index",
                reason="corrupt_index_blob",
                exc=exc,
            )
            return None
        idx = RunMemoryIndex(run_id=data.get("run_id", ""))
        for stage in data.get("stages", []):
            idx.stages.append(
                StagePointer(
                    stage_id=stage.get("stage_id", ""),
                    outcome=stage.get("outcome", ""),
                )
            )
        return idx

    @staticmethod
    def _encode_embedding(embedding: list[float] | bytes | None) -> bytes | None:
        if embedding is None:
            return None
        if isinstance(embedding, bytes):
            return embedding
        if isinstance(embedding, list):
            return struct.pack(f"<{len(embedding)}d", *embedding)
        raise TypeError(
            f"L2RunMemoryIndexStore: unsupported embedding type {type(embedding).__name__}"
        )
