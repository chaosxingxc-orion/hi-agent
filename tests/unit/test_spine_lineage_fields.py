"""W33-F: Rule 12 spine lineage fields regression tests.

Covers StoredEvent and RunRecord additions of ``parent_run_id``,
``attempt_id``, and ``phase_id``:

- Default-empty construction succeeds (forward-compat).
- Explicit lineage values round-trip through dataclass serialization.
- ALTER TABLE migrations add the columns idempotently to old-schema DBs.
- SQL read-back preserves the lineage values across a write/read cycle.

Layer 1 (unit) — these touch only the dataclass + the SQLite store; no
external services. The migration test exercises a real on-disk SQLite
file but every byte is created and read inside the test fixture.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import asdict

from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.run_store import RunRecord, SQLiteRunStore

# ---------------------------------------------------------------------------
# Construction defaults
# ---------------------------------------------------------------------------


def test_stored_event_default_lineage_fields_empty() -> None:
    """StoredEvent constructs with default empty lineage fields."""
    evt = StoredEvent(
        event_id="e1",
        run_id="r1",
        sequence=0,
        event_type="started",
        payload_json="{}",
        tenant_id="t1",
    )
    assert evt.parent_run_id == ""
    assert evt.attempt_id == ""
    assert evt.phase_id == ""


def test_run_record_default_lineage_fields_empty() -> None:
    """RunRecord constructs with default empty lineage fields."""
    now = time.time()
    rec = RunRecord(
        run_id="r1",
        tenant_id="t1",
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=now,
        updated_at=now,
    )
    assert rec.parent_run_id == ""
    assert rec.attempt_id == ""
    assert rec.phase_id == ""


# ---------------------------------------------------------------------------
# Serialization round-trip via asdict (dataclasses stdlib).
# ---------------------------------------------------------------------------


def test_run_record_lineage_fields_round_trip_via_asdict() -> None:
    """Explicit lineage fields round-trip through asdict/RunRecord(**dict)."""
    now = time.time()
    attempt_id = str(uuid.uuid4())
    rec = RunRecord(
        run_id="r1",
        tenant_id="t1",
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=now,
        updated_at=now,
        parent_run_id="parent-run-42",
        attempt_id=attempt_id,
        phase_id="execute",
    )
    serialized = asdict(rec)
    assert serialized["parent_run_id"] == "parent-run-42"
    assert serialized["attempt_id"] == attempt_id
    assert serialized["phase_id"] == "execute"

    revived = RunRecord(**serialized)
    assert revived.parent_run_id == "parent-run-42"
    assert revived.attempt_id == attempt_id
    assert revived.phase_id == "execute"


def test_stored_event_lineage_fields_round_trip_via_asdict() -> None:
    """Explicit lineage fields round-trip through asdict/StoredEvent(**dict)."""
    attempt_id = str(uuid.uuid4())
    evt = StoredEvent(
        event_id="e1",
        run_id="r1",
        sequence=0,
        event_type="phase_change",
        payload_json="{}",
        tenant_id="t1",
        parent_run_id="parent-run-7",
        attempt_id=attempt_id,
        phase_id="finalize",
    )
    serialized = asdict(evt)
    assert serialized["parent_run_id"] == "parent-run-7"
    assert serialized["attempt_id"] == attempt_id
    assert serialized["phase_id"] == "finalize"

    revived = StoredEvent(**serialized)
    assert revived.parent_run_id == "parent-run-7"
    assert revived.attempt_id == attempt_id
    assert revived.phase_id == "finalize"


# ---------------------------------------------------------------------------
# Schema migration: open against an OLD schema, then construct the store.
# ---------------------------------------------------------------------------


def _create_old_run_records_schema(db_path: str) -> None:
    """Create a run_records table that lacks the W33-F lineage columns."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE run_records (
                run_id              TEXT    PRIMARY KEY,
                tenant_id           TEXT    NOT NULL,
                user_id             TEXT    NOT NULL DEFAULT '__legacy__',
                session_id          TEXT    NOT NULL DEFAULT '__legacy__',
                task_contract_json  TEXT    NOT NULL DEFAULT '',
                status              TEXT    NOT NULL DEFAULT 'queued',
                priority            INTEGER NOT NULL DEFAULT 5,
                attempt_count       INTEGER NOT NULL DEFAULT 0,
                cancellation_flag   INTEGER NOT NULL DEFAULT 0,
                result_summary      TEXT    NOT NULL DEFAULT '',
                error_summary       TEXT    NOT NULL DEFAULT '',
                created_at          REAL    NOT NULL,
                updated_at          REAL    NOT NULL
            );
            """
        )
        # Pre-existing row that must survive the migration.
        now = time.time()
        con.execute(
            "INSERT INTO run_records "
            "(run_id, tenant_id, user_id, session_id, task_contract_json, status, priority, "
            "attempt_count, cancellation_flag, result_summary, error_summary, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-run-1",
                "legacy-tenant",
                "u1",
                "s1",
                '{"task": "legacy"}',
                "queued",
                5,
                0,
                0,
                "",
                "",
                now,
                now,
            ),
        )
        con.commit()
    finally:
        con.close()


def _create_old_run_events_schema(db_path: str) -> None:
    """Create a run_events table that lacks the W33-F lineage columns."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE run_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id    TEXT    NOT NULL UNIQUE,
                run_id      TEXT    NOT NULL,
                sequence    INTEGER NOT NULL,
                event_type  TEXT    NOT NULL,
                payload_json TEXT   NOT NULL DEFAULT '',
                tenant_id   TEXT    NOT NULL,
                user_id     TEXT    NOT NULL DEFAULT '__legacy__',
                session_id  TEXT    NOT NULL DEFAULT '__legacy__',
                trace_id    TEXT    NOT NULL DEFAULT '',
                created_at  REAL    NOT NULL DEFAULT 0.0
            );
            """
        )
        # Pre-existing row that must survive the migration.
        con.execute(
            "INSERT INTO run_events "
            "(event_id, run_id, sequence, event_type, payload_json, tenant_id, "
            "user_id, session_id, trace_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-event-1",
                "legacy-run-1",
                0,
                "started",
                "{}",
                "legacy-tenant",
                "u1",
                "s1",
                "",
                time.time(),
            ),
        )
        con.commit()
    finally:
        con.close()


def test_run_store_migration_adds_lineage_columns_to_old_schema(tmp_path) -> None:
    """ALTER TABLE migration adds W33-F lineage columns without losing data."""
    db = str(tmp_path / "legacy_runs.db")
    _create_old_run_records_schema(db)

    # Prove the legacy DB lacks the new columns.
    con = sqlite3.connect(db)
    try:
        cols_before = {row[1] for row in con.execute("PRAGMA table_info(run_records)")}
    finally:
        con.close()
    assert "parent_run_id" not in cols_before
    assert "attempt_id" not in cols_before
    assert "phase_id" not in cols_before

    # Constructing the store triggers _migrate.
    store = SQLiteRunStore(db_path=db)
    try:
        # After migration, all 3 columns exist.
        cols_after = {
            row[1] for row in store._conn.execute("PRAGMA table_info(run_records)")
        }
        assert "parent_run_id" in cols_after
        assert "attempt_id" in cols_after
        assert "phase_id" in cols_after

        # The pre-existing row survived; reading it returns empty lineage values.
        legacy = store.get("legacy-run-1")
        assert legacy is not None
        assert legacy.run_id == "legacy-run-1"
        assert legacy.tenant_id == "legacy-tenant"
        assert legacy.parent_run_id == ""
        assert legacy.attempt_id == ""
        assert legacy.phase_id == ""
    finally:
        store.close()


def test_run_store_migration_is_idempotent(tmp_path) -> None:
    """Running the migration twice on the same DB is a no-op."""
    db = str(tmp_path / "idempotent_runs.db")
    _create_old_run_records_schema(db)

    # First open triggers the migration.
    store1 = SQLiteRunStore(db_path=db)
    try:
        cols_first = {
            row[1] for row in store1._conn.execute("PRAGMA table_info(run_records)")
        }
    finally:
        store1.close()

    # Second open finds the columns already there; _migrate skips ALTER.
    store2 = SQLiteRunStore(db_path=db)
    try:
        cols_second = {
            row[1] for row in store2._conn.execute("PRAGMA table_info(run_records)")
        }
        # No ValueError ('duplicate column name'), no schema drift.
        assert cols_second == cols_first

        # Legacy row still readable.
        legacy = store2.get("legacy-run-1")
        assert legacy is not None
        assert legacy.run_id == "legacy-run-1"
    finally:
        store2.close()


def test_event_store_migration_adds_lineage_columns_to_old_schema(tmp_path) -> None:
    """ALTER TABLE migration adds W33-F lineage columns to event_store."""
    db = str(tmp_path / "legacy_events.db")
    _create_old_run_events_schema(db)

    # Confirm legacy DB lacks the new columns.
    con = sqlite3.connect(db)
    try:
        cols_before = {row[1] for row in con.execute("PRAGMA table_info(run_events)")}
    finally:
        con.close()
    assert "parent_run_id" not in cols_before
    assert "attempt_id" not in cols_before
    assert "phase_id" not in cols_before

    # Constructing the store triggers migration.
    store = SQLiteEventStore(db_path=db)
    try:
        cols_after = {row[1] for row in store._conn.execute("PRAGMA table_info(run_events)")}
        assert "parent_run_id" in cols_after
        assert "attempt_id" in cols_after
        assert "phase_id" in cols_after

        # Legacy event row still readable; lineage fields default to empty.
        rows = store.list_since("legacy-run-1", since_sequence=-1)
        assert len(rows) == 1
        assert rows[0].event_id == "legacy-event-1"
        assert rows[0].parent_run_id == ""
        assert rows[0].attempt_id == ""
        assert rows[0].phase_id == ""
    finally:
        store.close()


def test_event_store_migration_is_idempotent(tmp_path) -> None:
    """Running the event_store migration twice is a no-op."""
    db = str(tmp_path / "idempotent_events.db")
    _create_old_run_events_schema(db)

    store1 = SQLiteEventStore(db_path=db)
    try:
        cols_first = {
            row[1] for row in store1._conn.execute("PRAGMA table_info(run_events)")
        }
    finally:
        store1.close()

    store2 = SQLiteEventStore(db_path=db)
    try:
        cols_second = {
            row[1] for row in store2._conn.execute("PRAGMA table_info(run_events)")
        }
        assert cols_second == cols_first

        rows = store2.list_since("legacy-run-1", since_sequence=-1)
        assert len(rows) == 1
        assert rows[0].event_id == "legacy-event-1"
    finally:
        store2.close()


# ---------------------------------------------------------------------------
# SQL read-back: insert with explicit lineage, query, assert preserved.
# ---------------------------------------------------------------------------


def test_run_store_lineage_fields_preserved_through_upsert_and_get(tmp_path) -> None:
    """Lineage fields survive a real SQLite write/read cycle."""
    db = str(tmp_path / "runs.db")
    store = SQLiteRunStore(db_path=db)
    try:
        now = time.time()
        attempt_id = str(uuid.uuid4())
        rec = RunRecord(
            run_id="r-child-1",
            tenant_id="t1",
            task_contract_json="{}",
            status="queued",
            priority=5,
            attempt_count=1,
            cancellation_flag=False,
            result_summary="",
            error_summary="",
            created_at=now,
            updated_at=now,
            parent_run_id="r-root-9",
            attempt_id=attempt_id,
            phase_id="execute",
        )
        store.upsert(rec)

        retrieved = store.get("r-child-1")
        assert retrieved is not None
        assert retrieved.parent_run_id == "r-root-9"
        assert retrieved.attempt_id == attempt_id
        assert retrieved.phase_id == "execute"

        # Cross-check via list_by_tenant — the same row, same fields.
        rows = store.list_by_tenant("t1")
        assert len(rows) == 1
        assert rows[0].parent_run_id == "r-root-9"
        assert rows[0].attempt_id == attempt_id
        assert rows[0].phase_id == "execute"
    finally:
        store.close()


def test_event_store_lineage_fields_preserved_through_append_and_list(tmp_path) -> None:
    """Lineage fields survive a real SQLite write/read cycle for events."""
    db = str(tmp_path / "events.db")
    store = SQLiteEventStore(db_path=db)
    try:
        attempt_id = str(uuid.uuid4())
        evt = StoredEvent(
            event_id="e-1",
            run_id="r1",
            sequence=0,
            event_type="phase_change",
            payload_json="{}",
            tenant_id="t1",
            parent_run_id="r-root-9",
            attempt_id=attempt_id,
            phase_id="finalize",
        )
        store.append(evt)

        events = store.list_since("r1", since_sequence=-1)
        assert len(events) == 1
        assert events[0].parent_run_id == "r-root-9"
        assert events[0].attempt_id == attempt_id
        assert events[0].phase_id == "finalize"

        # Also check the get_events dict-shaped path.
        dict_rows = store.get_events("r1", tenant_id="t1")
        assert len(dict_rows) == 1
        assert dict_rows[0]["parent_run_id"] == "r-root-9"
        assert dict_rows[0]["attempt_id"] == attempt_id
        assert dict_rows[0]["phase_id"] == "finalize"
    finally:
        store.close()
