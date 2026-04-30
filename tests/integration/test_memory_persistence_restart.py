"""Integration tests: L1/L2 memory persistence survives process restart.

W24-E / RIA A-07. Each test writes records, closes the store handle, opens
a fresh handle against the same SQLite file, and asserts the records are
still there.
"""

from __future__ import annotations

from pathlib import Path

from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.l1_store import L1CompressedMemoryStore
from hi_agent.memory.l2_index import RunMemoryIndex
from hi_agent.memory.l2_store import L2RunMemoryIndexStore


def test_l1_store_records_survive_restart(tmp_path: Path) -> None:
    """L1: write records, close, reopen — records still readable."""
    db_path = tmp_path / "l1_restart.sqlite"

    store_a = L1CompressedMemoryStore(db_path=db_path)
    mem_1 = CompressedStageMemory(
        stage_id="S1_understand",
        findings=["alpha", "beta"],
        decisions=["go-deep"],
        outcome="succeeded",
        compression_method="llm",
    )
    mem_2 = CompressedStageMemory(
        stage_id="S2_plan",
        findings=["gamma"],
        outcome="active",
    )
    store_a.register("tenant-acme", "run-42", "S1_understand", mem_1)
    store_a.register("tenant-acme", "run-42", "S2_plan", mem_2)
    store_a.close()

    # Simulate process restart: brand-new handle on the same file.
    store_b = L1CompressedMemoryStore(db_path=db_path)
    rows = store_b.query("tenant-acme", "run-42")
    assert len(rows) == 2
    stages = sorted(r.stage_id for r in rows)
    assert stages == ["S1_understand", "S2_plan"]
    by_stage = {r.stage_id: r for r in rows}
    assert by_stage["S1_understand"].findings == ["alpha", "beta"]
    assert by_stage["S1_understand"].decisions == ["go-deep"]
    assert by_stage["S1_understand"].outcome == "succeeded"
    assert by_stage["S1_understand"].compression_method == "llm"
    assert by_stage["S2_plan"].findings == ["gamma"]
    store_b.close()


def test_l1_store_tenant_isolation_survives_restart(tmp_path: Path) -> None:
    """L1: tenant scoping survives restart."""
    db_path = tmp_path / "l1_isolation.sqlite"

    store = L1CompressedMemoryStore(db_path=db_path)
    store.register("tA", "run-1", "S1", CompressedStageMemory(stage_id="S1"))
    store.register("tB", "run-1", "S1", CompressedStageMemory(stage_id="S1"))
    store.close()

    reopened = L1CompressedMemoryStore(db_path=db_path)
    assert len(reopened.query("tA", "run-1")) == 1
    assert len(reopened.query("tB", "run-1")) == 1
    assert reopened.query("tC", "run-1") == []
    reopened.close()


def test_l2_store_record_survives_restart(tmp_path: Path) -> None:
    """L2: write index, close, reopen — index still readable."""
    db_path = tmp_path / "l2_restart.sqlite"

    store_a = L2RunMemoryIndexStore(db_path=db_path)
    idx = RunMemoryIndex(run_id="run-42")
    idx.add_stage("S1_understand", "succeeded")
    idx.add_stage("S2_plan", "active")
    idx.add_stage("S3_act", "pending")
    store_a.register(
        tenant_id="tenant-acme",
        run_id="run-42",
        index=idx,
        embedding=[0.0, 1.5, -2.5, 4.0],
        summary_text="three-stage research run",
    )
    store_a.close()

    store_b = L2RunMemoryIndexStore(db_path=db_path)
    got = store_b.query("tenant-acme", "run-42")
    assert got is not None
    assert got.run_id == "run-42"
    assert len(got.stages) == 3
    assert [(p.stage_id, p.outcome) for p in got.stages] == [
        ("S1_understand", "succeeded"),
        ("S2_plan", "active"),
        ("S3_act", "pending"),
    ]
    assert store_b.query_summary("tenant-acme", "run-42") == "three-stage research run"
    store_b.close()


def test_l2_store_latest_wins_after_restart(tmp_path: Path) -> None:
    """L2: when multiple registers share (tenant, run), restart sees the latest."""
    db_path = tmp_path / "l2_latest.sqlite"

    store_a = L2RunMemoryIndexStore(db_path=db_path)
    first = RunMemoryIndex(run_id="r")
    first.add_stage("S1", "succeeded")
    store_a.register("t", "r", first, summary_text="first")

    second = RunMemoryIndex(run_id="r")
    second.add_stage("S1", "succeeded")
    second.add_stage("S2", "succeeded")
    store_a.register("t", "r", second, summary_text="second")
    store_a.close()

    store_b = L2RunMemoryIndexStore(db_path=db_path)
    got = store_b.query("t", "r")
    assert got is not None
    assert len(got.stages) == 2
    assert store_b.query_summary("t", "r") == "second"
    store_b.close()


def test_builder_l1_l2_stores_under_research_posture(
    tmp_path: Path, monkeypatch
) -> None:
    """Builder wires durable SQLite stores under research/prod posture (Rule 11).

    Verifies that ``_build_l1_store()`` / ``_build_l2_store()`` create files
    under ``episodic_storage_dir.parent / memory / L{1,2}/`` when posture is
    strict, and that records written through them survive a fresh builder.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    episodic_dir = tmp_path / "episodes"
    cfg = TraceConfig(episodic_storage_dir=str(episodic_dir))

    builder_a = SystemBuilder(cfg)
    l1_a = builder_a._build_l1_store()
    l2_a = builder_a._build_l2_store()

    expected_l1 = tmp_path / "memory" / "L1" / "l1_compressed.sqlite"
    expected_l2 = tmp_path / "memory" / "L2" / "l2_run_index.sqlite"
    assert Path(l1_a._path) == expected_l1
    assert Path(l2_a._path) == expected_l2
    assert expected_l1.exists()
    assert expected_l2.exists()

    l1_a.register("t", "r", "S1", CompressedStageMemory(stage_id="S1"))
    idx = RunMemoryIndex(run_id="r")
    idx.add_stage("S1", "succeeded")
    l2_a.register("t", "r", idx, summary_text="restart-test")
    l1_a.close()
    l2_a.close()

    # Fresh builder = fresh process simulation.
    builder_b = SystemBuilder(cfg)
    l1_b = builder_b._build_l1_store()
    l2_b = builder_b._build_l2_store()

    assert len(l1_b.query("t", "r")) == 1
    assert l2_b.query_summary("t", "r") == "restart-test"
    l1_b.close()
    l2_b.close()
