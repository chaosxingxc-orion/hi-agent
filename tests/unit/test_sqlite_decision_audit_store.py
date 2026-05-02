"""Unit tests for SqliteDecisionAuditStore.

Uses ':memory:' db_path so no filesystem I/O is needed.  The
persistence-across-connections test uses a temporary file to verify that
records survive closing and reopening the database.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from hi_agent.route_engine.decision_audit_store import SqliteDecisionAuditStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> SqliteDecisionAuditStore:
    """In-memory store, fresh for each test."""
    return SqliteDecisionAuditStore(db_path=":memory:")


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


def test_append_returns_normalized_copy(store: SqliteDecisionAuditStore) -> None:
    audit = {"run_id": "run-1", "stage_id": "stage-a", "route": "llm"}
    result = store.append(audit)
    assert result["run_id"] == "run-1"
    assert result["stage_id"] == "stage-a"
    assert result["route"] == "llm"


def test_append_strips_whitespace(store: SqliteDecisionAuditStore) -> None:
    audit = {"run_id": "  run-1  ", "stage_id": " stage-a ", "x": 1}
    result = store.append(audit)
    assert result["run_id"] == "run-1"
    assert result["stage_id"] == "stage-a"


def test_append_rejects_non_mapping(store: SqliteDecisionAuditStore) -> None:
    with pytest.raises(TypeError):
        store.append(["run_id", "stage_id"])  # type: ignore[arg-type]  expiry_wave: Wave 30


def test_append_rejects_missing_run_id(store: SqliteDecisionAuditStore) -> None:
    with pytest.raises(ValueError):
        store.append({"stage_id": "s"})


def test_append_rejects_empty_stage_id(store: SqliteDecisionAuditStore) -> None:
    with pytest.raises(ValueError):
        store.append({"run_id": "r", "stage_id": "  "})


# ---------------------------------------------------------------------------
# list_by_run
# ---------------------------------------------------------------------------


def test_list_by_run_returns_insertion_order(store: SqliteDecisionAuditStore) -> None:
    store.append({"run_id": "r1", "stage_id": "s1", "seq": 1})
    store.append({"run_id": "r1", "stage_id": "s2", "seq": 2})
    store.append({"run_id": "r1", "stage_id": "s1", "seq": 3})

    records = store.list_by_run("r1")
    assert len(records) == 3
    assert [r["seq"] for r in records] == [1, 2, 3]


def test_list_by_run_empty_for_unknown_run(store: SqliteDecisionAuditStore) -> None:
    store.append({"run_id": "r1", "stage_id": "s1"})
    assert store.list_by_run("r-unknown") == []


def test_list_by_run_different_runs_dont_bleed(store: SqliteDecisionAuditStore) -> None:
    store.append({"run_id": "r1", "stage_id": "s1", "val": "a"})
    store.append({"run_id": "r2", "stage_id": "s1", "val": "b"})

    assert len(store.list_by_run("r1")) == 1
    assert store.list_by_run("r1")[0]["val"] == "a"
    assert len(store.list_by_run("r2")) == 1
    assert store.list_by_run("r2")[0]["val"] == "b"


# ---------------------------------------------------------------------------
# latest_by_stage
# ---------------------------------------------------------------------------


def test_latest_by_stage_returns_most_recent(store: SqliteDecisionAuditStore) -> None:
    store.append({"run_id": "r1", "stage_id": "s1", "seq": 1})
    store.append({"run_id": "r1", "stage_id": "s1", "seq": 2})

    latest = store.latest_by_stage("r1", "s1")
    assert latest is not None
    assert latest["seq"] == 2


def test_latest_by_stage_returns_none_when_absent(store: SqliteDecisionAuditStore) -> None:
    store.append({"run_id": "r1", "stage_id": "s1"})
    assert store.latest_by_stage("r1", "s-missing") is None


def test_latest_by_stage_scoped_to_run(store: SqliteDecisionAuditStore) -> None:
    store.append({"run_id": "r1", "stage_id": "s1", "seq": 10})
    store.append({"run_id": "r2", "stage_id": "s1", "seq": 20})

    assert store.latest_by_stage("r1", "s1")["seq"] == 10  # type: ignore[index]  expiry_wave: Wave 30
    assert store.latest_by_stage("r2", "s1")["seq"] == 20  # type: ignore[index]


# ---------------------------------------------------------------------------
# Persistence across connections (file-backed)
# ---------------------------------------------------------------------------


def test_persistence_across_connections() -> None:
    """Records written to a file-backed DB survive closing and reopening."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store1 = SqliteDecisionAuditStore(db_path=db_path)
        store1.append({"run_id": "r1", "stage_id": "s1", "marker": "hello"})
        store1.close()

        store2 = SqliteDecisionAuditStore(db_path=db_path)
        records = store2.list_by_run("r1")
        store2.close()

        assert len(records) == 1
        assert records[0]["marker"] == "hello"
    finally:
        os.unlink(db_path)
