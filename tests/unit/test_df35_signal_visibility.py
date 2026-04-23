"""DF-35 regression: silent LLM compression fallbacks emit Rule-14 signals."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hi_agent.evolve.contracts import RunPostmortem
from hi_agent.evolve.skill_extractor import SkillExtractor
from hi_agent.memory.compressor import MemoryCompressor
from hi_agent.memory.l0_raw import RawEventRecord
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events


def _make_records(n: int) -> list[RawEventRecord]:
    return [
        RawEventRecord(
            event_type="StageStateChanged",
            payload={"stage_id": "s1", "to_state": "running", "idx": i},
        )
        for i in range(n)
    ]


def test_memory_compressor_sync_llm_json_parse_records_fallback() -> None:
    run_id = "test-df35-mem-sync-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    response = MagicMock()
    response.content = "not valid json at all {{{"
    gateway.complete.return_value = response

    compressor = MemoryCompressor(gateway=gateway, compress_threshold=1)
    result = compressor.compress_stage("s1", _make_records(3), run_id=run_id)

    assert result.compression_method == "fallback"
    events = get_fallback_events(run_id)
    assert any(event["reason"] == "llm_json_parse_error" for event in events), events
    match = next(event for event in events if event["reason"] == "llm_json_parse_error")
    assert match["kind"] == "heuristic"
    assert match["extra"]["stage_id"] == "s1"
    assert "compress_stage" in match["extra"]["site"]


def test_skill_extractor_llm_json_parse_records_fallback() -> None:
    run_id = "test-df35-skill-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    response = MagicMock()
    response.content = "}}} not a json array {{{"
    gateway.complete.return_value = response

    extractor = SkillExtractor(gateway=gateway)
    postmortem = RunPostmortem(
        run_id=run_id,
        task_id="task-001",
        task_family="quick_task",
        outcome="completed",
        stages_completed=["s1"],
        stages_failed=[],
        branches_explored=1,
        branches_pruned=0,
        total_actions=3,
        failure_codes=[],
        duration_seconds=1.0,
    )

    extractor.extract(postmortem)

    events = get_fallback_events(run_id)
    assert any(event["reason"] == "llm_json_parse_error" for event in events), events
    match = next(event for event in events if event["reason"] == "llm_json_parse_error")
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "skill_extractor._parse_llm_skills"
    assert match["extra"]["task_family"] == "quick_task"


@pytest.mark.asyncio
async def test_memory_compressor_async_gateway_json_parse_records_fallback() -> None:
    run_id = "test-df35-mem-async-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    response = MagicMock()
    response.content = "definitely not json"
    gateway.complete.return_value = response

    compressor = MemoryCompressor(gateway=gateway, compress_threshold=1, timeout_s=5.0)
    result = await compressor.acompress_stage("s1", _make_records(3), run_id=run_id)

    assert result.compression_method == "fallback"
    events = get_fallback_events(run_id)
    assert any(event["reason"] == "llm_json_parse_error" for event in events), events
