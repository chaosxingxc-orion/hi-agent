"""Tests for memory subsystem."""

from hi_agent.memory import MemoryCompressor, RawEventRecord, RawMemoryStore, RunMemoryIndex


def test_raw_memory_store_append_and_list() -> None:
    """Raw memory store should preserve insertion order."""
    store = RawMemoryStore()
    record = RawEventRecord(event_type="StageOpened", payload={"stage_id": "S1"})
    store.append(record)

    listed = store.list_all()
    assert len(listed) == 1
    assert listed[0].event_type == "StageOpened"


def test_memory_compressor_and_index() -> None:
    """Compressor should build stage findings and index should track pointers."""
    records = [
        RawEventRecord(
            event_type="StageStateChanged",
            payload={
                "stage_id": "S1_understand",
                "from_state": "pending",
                "to_state": "completed",
            },
        )
    ]
    compressed = MemoryCompressor().compress_stage_sync("S1_understand", records)
    index = RunMemoryIndex(run_id="run-1")
    index.add_stage("S1_understand", compressed.outcome)

    assert compressed.outcome == "succeeded"
    assert index.stages[0].stage_id == "S1_understand"
