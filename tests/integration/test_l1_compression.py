"""Memory compression integration tests.

Validates L1 compression including:
- Compression of 30+ evidence records with summary quality
- Fallback path when LLM function fails
- Contradiction preservation in compressed summaries
- Compression integrated with real runner flow
"""

from __future__ import annotations

import asyncio
import json

from hi_agent.contracts import TaskContract
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord, RawMemoryStore
from hi_agent.runner import STAGES, RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_evidence_records(
    stage_id: str,
    count: int,
    *,
    include_task_view: bool = False,
) -> list[RawEventRecord]:
    """Generate synthetic evidence records for a stage."""
    records: list[RawEventRecord] = []
    for _ in range(count):
        records.append(
            RawEventRecord(
                event_type="StageStateChanged",
                payload={"stage_id": stage_id, "to_state": "active"},
            )
        )
    if include_task_view:
        records.append(
            RawEventRecord(
                event_type="TaskViewRecorded",
                payload={"stage_id": stage_id, "task_view_id": f"tv-{stage_id}"},
            )
        )
    # Add a final completed record
    records.append(
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": stage_id, "to_state": "completed"},
        )
    )
    return records


class TestCompressionOf30PlusRecords:
    """Generate 30+ evidence records, compress, verify summary quality."""

    def test_sync_compression_above_threshold(self) -> None:
        """Sync compression with 30+ records should use fallback path."""
        records = _make_evidence_records("S2_gather", 30, include_task_view=True)
        compressor = MemoryCompressor(compress_threshold=25)

        result = compressor.compress_stage("S2_gather", records)

        assert result.stage_id == "S2_gather"
        assert result.source_evidence_count == len(records)
        assert result.compression_method == "fallback"
        assert len(result.findings) > 0

    def test_sync_compression_below_threshold_uses_direct(self) -> None:
        """Records below threshold should use direct compression."""
        records = _make_evidence_records("S1_understand", 10, include_task_view=True)
        compressor = MemoryCompressor(compress_threshold=25)

        result = compressor.compress_stage("S1_understand", records)

        assert result.compression_method == "direct"
        assert result.source_evidence_count == len(records)

    def test_compression_findings_not_empty(self) -> None:
        """Compressed summary should contain meaningful findings."""
        records = _make_evidence_records("S3_build", 35, include_task_view=True)
        compressor = MemoryCompressor(compress_threshold=25)

        result = compressor.compress_stage("S3_build", records)

        assert len(result.findings) > 0
        assert any("S3_build" in f for f in result.findings)

    def test_compression_outcome_reflects_completed(self) -> None:
        """Outcome should be 'succeeded' when records contain 'completed'."""
        records = _make_evidence_records("S4_synthesize", 5, include_task_view=True)
        compressor = MemoryCompressor(compress_threshold=25)

        result = compressor.compress_stage("S4_synthesize", records)

        assert result.outcome == "succeeded"

    def test_compression_outcome_reflects_failed(self) -> None:
        """Outcome should be 'failed' when records contain a 'failed' StageStateChanged event.

        This covers the fix for A-1: _heuristic_compress must derive 'failed'
        from event records so callers don't need to override outcome post-hoc.
        """
        records = [
            RawEventRecord(
                event_type="StageStateChanged",
                payload={"stage_id": "S2_gather", "to_state": "active"},
            ),
            RawEventRecord(
                event_type="StageStateChanged",
                payload={"stage_id": "S2_gather", "to_state": "failed"},
            ),
        ]
        compressor = MemoryCompressor(compress_threshold=25)

        result = compressor.compress_stage("S2_gather", records)

        assert result.outcome == "failed", (
            f"Compressor must derive 'failed' outcome from StageStateChanged:failed records, "
            f"got {result.outcome!r}"
        )

    def test_compression_outcome_active_when_no_terminal_state(self) -> None:
        """Outcome should be 'active' when no terminal StageStateChanged event exists."""
        records = [
            RawEventRecord(
                event_type="StageStateChanged",
                payload={"stage_id": "S1_understand", "to_state": "active"},
            ),
        ]
        compressor = MemoryCompressor(compress_threshold=25)

        result = compressor.compress_stage("S1_understand", records)

        assert result.outcome == "active"

    def test_async_compression_above_threshold_no_llm(self) -> None:
        """Async compression without LLM should use fallback path."""
        records = _make_evidence_records("S3_build", 30)
        compressor = MemoryCompressor(compress_threshold=25, llm_fn=None)

        result = asyncio.run(compressor.acompress_stage("S3_build", records))

        assert result.compression_method == "fallback"
        assert result.source_evidence_count == len(records)


class TestFallbackPath:
    """LLM failure triggers fallback compression."""

    def test_failing_llm_triggers_fallback(self) -> None:
        """A failing LLM function should fall back to truncation."""

        async def failing_llm(prompt: str) -> str:
            raise RuntimeError("LLM unavailable")

        records = _make_evidence_records("S2_gather", 30)
        compressor = MemoryCompressor(
            llm_fn=failing_llm,
            compress_threshold=25,
            timeout_s=2.0,
        )

        result = asyncio.run(compressor.acompress_stage("S2_gather", records))

        assert result.compression_method == "fallback"
        assert result.source_evidence_count == len(records)

    def test_timeout_llm_triggers_fallback(self) -> None:
        """An LLM that times out should fall back to truncation."""

        async def slow_llm(prompt: str) -> str:
            await asyncio.sleep(10.0)
            return "{}"

        records = _make_evidence_records("S1_understand", 30)
        compressor = MemoryCompressor(
            llm_fn=slow_llm,
            compress_threshold=25,
            timeout_s=0.1,
        )

        result = asyncio.run(compressor.acompress_stage("S1_understand", records))

        assert result.compression_method == "fallback"

    def test_successful_llm_uses_llm_method(self) -> None:
        """A successful LLM response should use 'llm' compression method."""

        async def good_llm(prompt: str) -> str:
            return json.dumps(
                {
                    "findings": ["llm-finding-1"],
                    "decisions": ["llm-decision-1"],
                    "outcome": "succeeded",
                    "contradiction_refs": [],
                    "key_entities": ["entity-1"],
                }
            )

        records = _make_evidence_records("S3_build", 30)
        compressor = MemoryCompressor(
            llm_fn=good_llm,
            compress_threshold=25,
            timeout_s=5.0,
        )

        result = asyncio.run(compressor.acompress_stage("S3_build", records))

        assert result.compression_method == "llm"
        assert "llm-finding-1" in result.findings
        assert result.outcome == "succeeded"


class TestContradictionPreservation:
    """Contradiction tags should survive compression."""

    def test_contradictory_evidence_tagged(self) -> None:
        """Records with negation pairs should get contradiction tags."""
        store = RawMemoryStore()
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"stage_id": "S2_gather", "result": "success"},
            ),
            stage_id="S2_gather",
        )
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"stage_id": "S2_gather", "result": "failure"},
            ),
            stage_id="S2_gather",
        )

        records = store.list_all()
        # The second record should have contradiction tags
        assert len(records[1].tags) > 0
        assert any(t.startswith("contradiction:") for t in records[1].tags)

    def test_contradiction_refs_in_compressed_summary(self) -> None:
        """Compression should preserve contradiction_refs from tagged records."""
        store = RawMemoryStore()
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"stage_id": "S2_gather", "result": "success"},
            ),
            stage_id="S2_gather",
        )
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"stage_id": "S2_gather", "result": "failure"},
            ),
            stage_id="S2_gather",
        )

        compressor = MemoryCompressor(compress_threshold=100)
        records = store.list_all()
        result = compressor.compress_stage("S2_gather", records)

        assert len(result.contradiction_refs) > 0

    def test_no_contradiction_when_consistent(self) -> None:
        """Consistent records should not produce contradiction tags."""
        store = RawMemoryStore()
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"stage_id": "S2_gather", "result": "ok"},
            ),
            stage_id="S2_gather",
        )
        store.append(
            RawEventRecord(
                event_type="ActionExecuted",
                payload={"stage_id": "S2_gather", "result": "also ok"},
            ),
            stage_id="S2_gather",
        )

        records = store.list_all()
        assert all(len(r.tags) == 0 for r in records)


class TestCompressionWithRunnerFlow:
    """Compress stage memory from a real S1->S5 runner execution."""

    def test_each_stage_compresses_after_run(self) -> None:
        """After a full run, each stage should have a compressed summary."""
        contract = TaskContract(task_id="comp-run-001", goal="compress runner")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        result = executor.execute()

        assert result == "completed"
        # Runner stores compressed summaries for each stage
        assert len(executor.stage_summaries) == len(STAGES)
        for stage_id in STAGES:
            summary = executor.stage_summaries[stage_id]
            assert summary.stage_id == stage_id
            assert summary.outcome in {"succeeded", "active", "inconclusive"}

    def test_raw_memory_populated_during_run(self) -> None:
        """Raw memory store should have records for every stage."""
        contract = TaskContract(task_id="comp-run-002", goal="raw memory check")
        kernel = MockKernel(strict_mode=True)
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())

        executor.execute()

        all_records = executor.raw_memory.list_all()
        assert len(all_records) > 0
        stage_ids_in_memory = {
            r.payload.get("stage_id") for r in all_records if "stage_id" in r.payload
        }
        for stage_id in STAGES:
            assert stage_id in stage_ids_in_memory, f"No raw memory records for {stage_id}"

    def test_compressor_metrics_updated_after_run(self) -> None:
        """Compressor metrics should reflect the compression calls made."""
        contract = TaskContract(task_id="comp-run-003", goal="metrics check")
        kernel = MockKernel(strict_mode=True)
        compressor = MemoryCompressor()
        executor = RunExecutor(contract, kernel, compressor=compressor, raw_memory=RawMemoryStore())

        executor.execute()

        total = (
            compressor.metrics.compressed_count
            + compressor.metrics.fallback_count
            + compressor.metrics.direct_count
        )
        assert total == len(STAGES)
