"""Tests for four memory changes: H-2, M-1, M-3, H-1."""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hi_agent.memory.l0_raw import RawEventRecord, RawMemoryStore
from hi_agent.memory.l0_summarizer import L0Summarizer
from hi_agent.memory.long_term import LongTermMemoryGraph, MemoryNode


# ===========================================================================
# H-2: LongTermMemoryGraph auto-load on init
# ===========================================================================


def test_h2_auto_load_on_init(tmp_path: Path) -> None:
    """Node persisted by one instance is visible on a fresh instance without load()."""
    graph_file = str(tmp_path / "graph.json")

    g1 = LongTermMemoryGraph(storage_path=graph_file)
    node = MemoryNode(node_id="n1", content="hello world", node_type="fact")
    g1.add_node(node)
    g1.save()

    # New instance — must auto-load
    g2 = LongTermMemoryGraph(storage_path=graph_file)
    assert g2.node_count() == 1
    assert g2.get_node("n1") is not None
    assert g2.get_node("n1").content == "hello world"


def test_h2_no_error_when_file_absent(tmp_path: Path) -> None:
    """Constructor must not raise when the JSON file does not exist yet."""
    graph_file = str(tmp_path / "nonexistent" / "graph.json")
    g = LongTermMemoryGraph(storage_path=graph_file)
    assert g.node_count() == 0


# ===========================================================================
# M-1: RawMemoryStore close() + context manager
# ===========================================================================


def test_m1_close_closes_file_handle(tmp_path: Path) -> None:
    """close() flushes and closes the underlying file handle."""
    store = RawMemoryStore(run_id="run-close", base_dir=tmp_path)
    assert store._file is not None
    store.close()
    assert store._file is None


def test_m1_close_is_idempotent(tmp_path: Path) -> None:
    """Calling close() twice must not raise."""
    store = RawMemoryStore(run_id="run-idem", base_dir=tmp_path)
    store.close()
    store.close()  # second call — must not raise


def test_m1_append_after_close_raises(tmp_path: Path) -> None:
    """append() after close() raises ValueError when a run_id was given."""
    store = RawMemoryStore(run_id="run-closed", base_dir=tmp_path)
    store.close()
    with pytest.raises(ValueError, match="closed"):
        store.append(RawEventRecord(event_type="X", payload={}))


def test_m1_append_on_in_memory_store_never_raises() -> None:
    """append() on a store without run_id never raises (no file to close)."""
    store = RawMemoryStore()
    store.close()  # no-op
    # Must NOT raise — no run_id means the closed check is not triggered
    store.append(RawEventRecord(event_type="X", payload={}))


def test_m1_context_manager(tmp_path: Path) -> None:
    """Context manager closes the store on exit."""
    with RawMemoryStore(run_id="run-ctx", base_dir=tmp_path) as store:
        store.append(RawEventRecord(event_type="Y", payload={"k": 1}))
    # After exiting the context, the file handle should be closed
    assert store._file is None
    # JSONL file must exist with the written record
    log_file = tmp_path / "logs" / "memory" / "L0" / "run-ctx.jsonl"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["metadata"]["event_type"] == "Y"


# ===========================================================================
# M-3: L0Summarizer
# ===========================================================================


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts as JSONL lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_m3_summarize_stage_complete_events(tmp_path: Path) -> None:
    """stage_complete events produce tasks_completed and key_learnings entries."""
    run_id = "run-sum-001"
    log_path = tmp_path / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
    records = [
        {
            "timestamp": "2026-04-15T00:00:00+00:00",
            "run_id": run_id,
            "content": {"stage_id": "understand", "result": "analysis done"},
            "metadata": {"event_type": "stage_complete", "tags": []},
        },
        {
            "timestamp": "2026-04-15T00:01:00+00:00",
            "run_id": run_id,
            "content": {"stage_id": "synthesize", "result": "synthesis done"},
            "metadata": {"event_type": "stage_complete", "tags": []},
        },
    ]
    _write_jsonl(log_path, records)

    summary = L0Summarizer().summarize_run(run_id, tmp_path)
    assert summary is not None
    assert "understand" in summary.tasks_completed
    assert "synthesize" in summary.tasks_completed
    assert len(summary.key_learnings) == 2


def test_m3_summarize_pattern_events(tmp_path: Path) -> None:
    """reflection/insight/pattern events populate patterns_observed."""
    run_id = "run-sum-002"
    log_path = tmp_path / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
    records = [
        {
            "timestamp": "2026-04-15T00:00:00+00:00",
            "run_id": run_id,
            "content": {"message": "retries help"},
            "metadata": {"event_type": "reflection", "tags": []},
        },
        {
            "timestamp": "2026-04-15T00:01:00+00:00",
            "run_id": run_id,
            "content": {"message": "caching reduces cost"},
            "metadata": {"event_type": "insight", "tags": []},
        },
    ]
    _write_jsonl(log_path, records)

    summary = L0Summarizer().summarize_run(run_id, tmp_path)
    assert summary is not None
    assert len(summary.patterns_observed) == 2


def test_m3_empty_file_returns_none(tmp_path: Path) -> None:
    """An empty JSONL file returns None."""
    run_id = "run-empty"
    log_path = tmp_path / "logs" / "memory" / "L0" / f"{run_id}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    result = L0Summarizer().summarize_run(run_id, tmp_path)
    assert result is None


def test_m3_nonexistent_file_returns_none(tmp_path: Path) -> None:
    """A missing JSONL file returns None."""
    result = L0Summarizer().summarize_run("no-such-run", tmp_path)
    assert result is None


# ===========================================================================
# H-1: TF-IDF semantic search + embedding_fn
# ===========================================================================


def _make_node(node_id: str, content: str, **kwargs) -> MemoryNode:
    return MemoryNode(node_id=node_id, content=content, **kwargs)


def test_h1_tfidf_ranks_relevant_higher(tmp_path: Path) -> None:
    """TF-IDF ranks a node whose content matches query terms above an unrelated one."""
    g = LongTermMemoryGraph(storage_path=str(tmp_path / "g.json"))
    g.add_node(_make_node("n1", "machine learning neural network training"))
    g.add_node(_make_node("n2", "cooking recipe pasta tomato sauce"))

    results = g.search("neural network")
    assert len(results) >= 1
    assert results[0].node_id == "n1", "Relevant node must rank first"


def test_h1_tfidf_index_rebuilt_on_load(tmp_path: Path) -> None:
    """After save+load, TF-IDF index is rebuilt and search still works."""
    graph_file = str(tmp_path / "g2.json")
    g1 = LongTermMemoryGraph(storage_path=graph_file)
    g1.add_node(_make_node("n1", "python asyncio coroutine event loop"))
    g1.add_node(_make_node("n2", "database sql schema migration"))
    g1.save()

    g2 = LongTermMemoryGraph(storage_path=graph_file)
    results = g2.search("asyncio coroutine")
    assert results[0].node_id == "n1"


def test_h1_embedding_fn_used_when_provided() -> None:
    """When embedding_fn is set, it is called during search."""
    call_log: list[str] = []

    def fake_embed(text: str) -> list[float]:
        call_log.append(text)
        # Return a unit vector based on whether text contains 'cat'
        return [1.0, 0.0] if "cat" in text.lower() else [0.0, 1.0]

    g = LongTermMemoryGraph(embedding_fn=fake_embed)
    g.add_node(_make_node("n1", "cat and dog"))
    g.add_node(_make_node("n2", "car and bus"))

    call_log.clear()
    results = g.search("cat")
    # embedding_fn must have been called for both the query and at least one node
    assert len(call_log) >= 2
    assert results[0].node_id == "n1", "Cat node should rank higher for 'cat' query"


def test_h1_keyword_fallback_when_index_empty() -> None:
    """When TF-IDF index is empty (no nodes), falls back gracefully."""
    g = LongTermMemoryGraph()
    results = g.search("anything")
    assert results == []


def test_h1_cosine_similarity_correct() -> None:
    """Cosine similarity between identical vectors == 1, orthogonal == 0."""
    from hi_agent.memory.long_term import _cosine

    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_h1_new_constructor_signature_backward_compatible(tmp_path: Path) -> None:
    """Existing callers that pass only storage_path and profile_id still work."""
    g1 = LongTermMemoryGraph()
    g2 = LongTermMemoryGraph(storage_path=str(tmp_path / "g.json"))
    g3 = LongTermMemoryGraph(
        storage_path=str(tmp_path / "base" / "memory" / "long_term" / "graph.json"),
        profile_id="user-123",
    )
    assert g1.node_count() == 0
    assert g2.node_count() == 0
    assert g3.node_count() == 0
