"""Unit tests for L2RunMemoryIndexStore (W24-E / RIA A-07)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hi_agent.memory.l2_index import RunMemoryIndex, StagePointer
from hi_agent.memory.l2_store import L2RunMemoryIndexStore


def test_schema_created_on_init(tmp_path: Path) -> None:
    """The DDL creates the l2_run_memory_index table and its index."""
    db_path = tmp_path / "l2.sqlite"
    store = L2RunMemoryIndexStore(db_path=db_path)
    try:
        with sqlite3.connect(str(db_path)) as con:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        assert "l2_run_memory_index" in tables
        assert "idx_l2_tenant_run" in indexes
    finally:
        store.close()


def test_register_returns_row_id() -> None:
    """register() inserts a row and returns the auto-generated id."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    idx = RunMemoryIndex(run_id="run-1")
    idx.add_stage("S1", "succeeded")
    rid = store.register(tenant_id="t1", run_id="run-1", index=idx)
    assert rid > 0


def test_register_query_round_trip() -> None:
    """A registered RunMemoryIndex survives a query() round trip."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    idx = RunMemoryIndex(run_id="run-A")
    idx.add_stage("S1_understand", "succeeded")
    idx.add_stage("S2_plan", "active")
    store.register(tenant_id="tenant-x", run_id="run-A", index=idx)

    got = store.query(tenant_id="tenant-x", run_id="run-A")
    assert got is not None
    assert got.run_id == "run-A"
    assert len(got.stages) == 2
    assert got.stages[0] == StagePointer(stage_id="S1_understand", outcome="succeeded")
    assert got.stages[1] == StagePointer(stage_id="S2_plan", outcome="active")


def test_query_returns_none_when_missing() -> None:
    """Querying a (tenant, run) with no rows returns None."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    assert store.query(tenant_id="tenant-y", run_id="missing") is None


def test_query_filters_by_tenant_and_run() -> None:
    """Records are scoped strictly by (tenant_id, run_id)."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    idx = RunMemoryIndex(run_id="r1")
    idx.add_stage("S", "ok")
    store.register("tA", "r1", idx)
    store.register("tA", "r2", RunMemoryIndex(run_id="r2"))
    store.register("tB", "r1", RunMemoryIndex(run_id="r1"))

    assert store.query("tA", "r1") is not None
    assert store.query("tA", "r2") is not None
    assert store.query("tB", "r1") is not None
    assert store.query("tA", "missing") is None


def test_register_replaces_returns_latest() -> None:
    """When (tenant, run) is re-registered, query() returns the latest row."""
    store = L2RunMemoryIndexStore(db_path=":memory:")

    first = RunMemoryIndex(run_id="r")
    first.add_stage("S1", "succeeded")
    store.register("t", "r", first, summary_text="first")

    second = RunMemoryIndex(run_id="r")
    second.add_stage("S1", "succeeded")
    second.add_stage("S2", "active")
    store.register("t", "r", second, summary_text="second")

    got = store.query("t", "r")
    assert got is not None
    assert len(got.stages) == 2
    assert store.query_summary("t", "r") == "second"


def test_register_with_embedding_round_trip() -> None:
    """Embeddings (list[float]) are accepted and persisted alongside the index."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    idx = RunMemoryIndex(run_id="r")
    idx.add_stage("S1", "succeeded")
    embedding = [0.1, -0.5, 1.25, 3.0]
    store.register("t", "r", idx, embedding=embedding, summary_text="hello")

    got = store.query("t", "r")
    assert got is not None
    assert got.stages[0].stage_id == "S1"
    assert store.query_summary("t", "r") == "hello"


def test_register_rejects_missing_scope() -> None:
    """Empty tenant_id or run_id raises ValueError (Rule 6 / 12)."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    idx = RunMemoryIndex(run_id="r")
    with pytest.raises(ValueError):
        store.register(tenant_id="", run_id="r", index=idx)
    with pytest.raises(ValueError):
        store.register(tenant_id="t", run_id="", index=idx)


def test_init_rejects_empty_db_path() -> None:
    """Empty db_path raises ValueError (Rule 6)."""
    with pytest.raises(ValueError):
        L2RunMemoryIndexStore(db_path="")


def test_register_accepts_dict_payload() -> None:
    """register() also accepts dict payloads."""
    store = L2RunMemoryIndexStore(db_path=":memory:")
    payload = {
        "run_id": "r",
        "stages": [{"stage_id": "S1", "outcome": "succeeded"}],
    }
    store.register("t", "r", index=payload)
    got = store.query("t", "r")
    assert got is not None
    assert got.stages[0].stage_id == "S1"
