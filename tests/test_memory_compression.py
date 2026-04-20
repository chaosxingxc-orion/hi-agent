"""Tests for async LLM compression with fallback."""

from __future__ import annotations

import asyncio
import json

import pytest
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord, RawMemoryStore


def _make_records(n: int, stage_id: str = "S1") -> list[RawEventRecord]:
    """Generate *n* dummy raw event records."""
    records: list[RawEventRecord] = []
    for i in range(n):
        if i % 3 == 0:
            records.append(
                RawEventRecord(
                    event_type="StageStateChanged",
                    payload={
                        "stage_id": stage_id,
                        "from_state": "running",
                        "to_state": "completed" if i == n - 1 else "running",
                    },
                )
            )
        elif i % 3 == 1:
            records.append(
                RawEventRecord(
                    event_type="TaskViewRecorded",
                    payload={"task_view_id": f"tv-{i}"},
                )
            )
        else:
            records.append(
                RawEventRecord(
                    event_type="ActionExecuted",
                    payload={"action": f"action-{i}", "stage_id": stage_id},
                )
            )
    return records


# --------------------------------------------------------------------------- #
# Test 1: direct build (< 25 evidence)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_direct_build_below_threshold() -> None:
    """When evidence < threshold, build summary directly without LLM."""
    records = _make_records(10)
    compressor = MemoryCompressor(compress_threshold=25)

    result = await compressor.acompress_stage("S1", records)

    assert result.compression_method == "direct"
    assert result.source_evidence_count == 10
    assert len(result.findings) > 0
    assert result.stage_id == "S1"


# --------------------------------------------------------------------------- #
# Test 2: LLM compression (mock LLM function)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_llm_compression_with_mock() -> None:
    """When evidence >= threshold and LLM succeeds, use LLM result."""
    llm_response = json.dumps(
        {
            "findings": ["key finding A", "key finding B"],
            "decisions": ["decided X"],
            "outcome": "success",
            "contradiction_refs": [],
            "key_entities": ["entityA", "entityB"],
        }
    )

    async def mock_llm(prompt: str) -> str:
        return llm_response

    records = _make_records(30)
    compressor = MemoryCompressor(
        llm_fn=mock_llm,
        compress_threshold=25,
    )

    result = await compressor.acompress_stage("S2", records)

    assert result.compression_method == "llm"
    assert result.findings == ["key finding A", "key finding B"]
    assert result.decisions == ["decided X"]
    assert result.outcome == "success"
    assert result.key_entities == ["entityA", "entityB"]
    assert result.source_evidence_count == 30
    assert compressor.metrics.compressed_count == 1


# --------------------------------------------------------------------------- #
# Test 3: timeout fallback (LLM that takes 20s)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_timeout_fallback() -> None:
    """When LLM exceeds timeout, fallback to truncation."""

    async def slow_llm(prompt: str) -> str:
        await asyncio.sleep(20)
        return "{}"

    records = _make_records(30)
    compressor = MemoryCompressor(
        llm_fn=slow_llm,
        timeout_s=0.1,  # very short timeout for testing
        compress_threshold=25,
        fallback_items=20,
    )

    result = await compressor.acompress_stage("S1", records)

    assert result.compression_method == "fallback"
    assert result.source_evidence_count == 30
    assert compressor.metrics.fallback_count == 1
    assert compressor.metrics.compressed_count == 0


# --------------------------------------------------------------------------- #
# Test 4: LLM error fallback (LLM that raises)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_llm_error_fallback() -> None:
    """When LLM raises an exception, fallback to truncation."""

    async def failing_llm(prompt: str) -> str:
        raise RuntimeError("LLM service unavailable")

    records = _make_records(30)
    compressor = MemoryCompressor(
        llm_fn=failing_llm,
        compress_threshold=25,
        fallback_items=20,
    )

    result = await compressor.acompress_stage("S1", records)

    assert result.compression_method == "fallback"
    assert result.source_evidence_count == 30
    assert compressor.metrics.fallback_count == 1


# --------------------------------------------------------------------------- #
# Test 5: contradiction detection in L0
# --------------------------------------------------------------------------- #


def test_contradiction_detection_in_l0() -> None:
    """Adding a contradicting record should auto-tag it."""
    store = RawMemoryStore()

    store.append(
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "to_state": "success"},
        ),
        stage_id="S1",
    )
    store.append(
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "to_state": "failure"},
        ),
        stage_id="S1",
    )

    records = store.list_all()
    assert len(records) == 2
    # Second record should have a contradiction tag
    assert any(tag.startswith("contradiction:") for tag in records[1].tags)
    # First record should have no contradiction tags
    assert not any(tag.startswith("contradiction:") for tag in records[0].tags)


def test_no_contradiction_different_stage() -> None:
    """Records in different stages should not trigger contradiction."""
    store = RawMemoryStore()

    store.append(
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "to_state": "success"},
        ),
        stage_id="S1",
    )
    store.append(
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S2", "to_state": "failure"},
        ),
        stage_id="S2",
    )

    records = store.list_all()
    assert not any(tag.startswith("contradiction:") for tag in records[1].tags)


# --------------------------------------------------------------------------- #
# Test 6: compression metrics tracking
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_compression_metrics_tracking() -> None:
    """Metrics should accumulate across multiple compressions."""
    llm_response = json.dumps(
        {
            "findings": ["f1"],
            "decisions": [],
            "outcome": "success",
            "contradiction_refs": [],
            "key_entities": [],
        }
    )

    async def mock_llm(prompt: str) -> str:
        return llm_response

    compressor = MemoryCompressor(
        llm_fn=mock_llm,
        compress_threshold=5,
        fallback_items=3,
    )

    # Direct compression (below threshold)
    small_records = _make_records(3)
    await compressor.acompress_stage("S1", small_records)

    assert compressor.metrics.direct_count == 1
    assert compressor.metrics.compressed_count == 0
    assert compressor.metrics.fallback_count == 0

    # LLM compression (above threshold)
    large_records = _make_records(10)
    await compressor.acompress_stage("S2", large_records)

    assert compressor.metrics.direct_count == 1
    assert compressor.metrics.compressed_count == 1
    assert compressor.metrics.fallback_count == 0
    assert compressor.metrics.avg_compression_ratio > 0


@pytest.mark.asyncio
async def test_no_llm_fn_uses_fallback() -> None:
    """When no llm_fn is provided and evidence >= threshold, use fallback."""
    records = _make_records(30)
    compressor = MemoryCompressor(
        llm_fn=None,
        compress_threshold=25,
    )

    result = await compressor.acompress_stage("S1", records)

    assert result.compression_method == "fallback"
    assert compressor.metrics.fallback_count == 1


def test_sync_compress_stage_backward_compat() -> None:
    """The sync compress_stage method should work for runner.py compat."""
    records = _make_records(10)
    compressor = MemoryCompressor(compress_threshold=25)

    result = compressor.compress_stage("S1", records)

    assert result.compression_method == "direct"
    assert result.source_evidence_count == 10
