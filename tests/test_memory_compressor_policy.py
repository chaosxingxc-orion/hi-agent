"""Policy tests for memory compressor truncation behavior."""

from hi_agent.memory import MemoryCompressor, RawEventRecord


def test_compressor_keeps_full_records_below_threshold() -> None:
    """When evidence count is below threshold, all records are considered."""
    records = [
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "from_state": "pending", "to_state": "completed"},
        ),
        RawEventRecord(event_type="TaskViewRecorded", payload={"task_view_id": "tv-1"}),
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "from_state": "completed", "to_state": "running"},
        ),
    ]

    compressed = MemoryCompressor(compress_threshold=4, fallback_items=1).compress_stage_sync(
        "S1", records
    )

    assert compressed.findings == ["S1:completed", "S1:running"]
    assert compressed.decisions == ["task_view:tv-1"]


def test_compressor_truncates_to_fallback_items_at_threshold() -> None:
    """When evidence count reaches threshold, compressor falls back to truncated source."""
    records = [
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "from_state": "pending", "to_state": "completed"},
        ),
        RawEventRecord(event_type="TaskViewRecorded", payload={"task_view_id": "tv-early"}),
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "S1", "from_state": "completed", "to_state": "running"},
        ),
        RawEventRecord(event_type="TaskViewRecorded", payload={"task_view_id": "tv-late"}),
    ]

    compressed = MemoryCompressor(compress_threshold=4, fallback_items=2).compress_stage_sync(
        "S1", records
    )

    assert compressed.findings == ["S1:running"]
    assert compressed.decisions == ["task_view:tv-late"]
