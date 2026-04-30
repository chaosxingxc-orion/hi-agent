"""Unit tests for L1CompressedMemoryStore (W24-E / RIA A-07)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.l1_store import L1CompressedMemoryStore


def test_schema_created_on_init(tmp_path: Path) -> None:
    """The DDL creates the l1_compressed_memory table and its index."""
    db_path = tmp_path / "l1.sqlite"
    store = L1CompressedMemoryStore(db_path=db_path)
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
        assert "l1_compressed_memory" in tables
        assert "idx_l1_tenant_run" in indexes
    finally:
        store.close()


def test_register_returns_row_id() -> None:
    """register() inserts a row and returns the auto-generated id."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    mem = CompressedStageMemory(stage_id="S1", findings=["a", "b"])
    rid = store.register(tenant_id="t1", run_id="r1", stage_id="S1", memory=mem)
    assert rid > 0


def test_register_query_round_trip() -> None:
    """A registered CompressedStageMemory survives a query() round trip."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    mem = CompressedStageMemory(
        stage_id="S2_plan",
        findings=["finding-1", "finding-2"],
        decisions=["go-left"],
        outcome="succeeded",
        contradiction_refs=["c1"],
        key_entities=["entity-A"],
        source_evidence_count=3,
        compression_method="llm",
    )
    store.register(tenant_id="tenant-x", run_id="run-1", stage_id="S2_plan", memory=mem)

    rows = store.query(tenant_id="tenant-x", run_id="run-1")
    assert len(rows) == 1
    got = rows[0]
    assert got.stage_id == "S2_plan"
    assert got.findings == ["finding-1", "finding-2"]
    assert got.decisions == ["go-left"]
    assert got.outcome == "succeeded"
    assert got.contradiction_refs == ["c1"]
    assert got.key_entities == ["entity-A"]
    assert got.source_evidence_count == 3
    assert got.compression_method == "llm"


def test_query_empty_returns_empty_list() -> None:
    """Querying a tenant/run with no rows returns []."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    assert store.query(tenant_id="tenant-y", run_id="missing") == []


def test_query_filters_by_tenant_and_run() -> None:
    """Records are scoped strictly by (tenant_id, run_id)."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    store.register("tA", "r1", "S1", CompressedStageMemory(stage_id="S1"))
    store.register("tA", "r2", "S1", CompressedStageMemory(stage_id="S1"))
    store.register("tB", "r1", "S1", CompressedStageMemory(stage_id="S1"))

    assert len(store.query("tA", "r1")) == 1
    assert len(store.query("tA", "r2")) == 1
    assert len(store.query("tB", "r1")) == 1
    assert store.query("tA", "missing") == []


def test_register_preserves_insertion_order() -> None:
    """query() returns records in insertion order."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    for i in range(3):
        store.register(
            "t",
            "r",
            f"S{i}",
            CompressedStageMemory(stage_id=f"S{i}"),
        )
    rows = store.query("t", "r")
    assert [r.stage_id for r in rows] == ["S0", "S1", "S2"]


def test_register_rejects_missing_scope() -> None:
    """Empty tenant_id, run_id, or stage_id raises ValueError (Rule 6 / 12)."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    mem = CompressedStageMemory(stage_id="S1")
    with pytest.raises(ValueError):
        store.register(tenant_id="", run_id="r", stage_id="S1", memory=mem)
    with pytest.raises(ValueError):
        store.register(tenant_id="t", run_id="", stage_id="S1", memory=mem)
    with pytest.raises(ValueError):
        store.register(tenant_id="t", run_id="r", stage_id="", memory=mem)


def test_init_rejects_empty_db_path() -> None:
    """Empty db_path raises ValueError (Rule 6)."""
    with pytest.raises(ValueError):
        L1CompressedMemoryStore(db_path="")


def test_register_accepts_dict_payload() -> None:
    """register() also accepts dict and bytes payloads."""
    store = L1CompressedMemoryStore(db_path=":memory:")
    payload = {
        "stage_id": "S1",
        "findings": ["x"],
        "decisions": [],
        "outcome": "active",
        "contradiction_refs": [],
        "key_entities": [],
        "source_evidence_count": 0,
        "compression_method": "direct",
    }
    store.register("t", "r", "S1", memory=payload)
    rows = store.query("t", "r")
    assert len(rows) == 1
    assert rows[0].findings == ["x"]
