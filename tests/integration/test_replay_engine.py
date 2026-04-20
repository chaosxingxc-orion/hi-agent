"""Integration tests for the deterministic replay engine."""

from __future__ import annotations

import json
from dataclasses import asdict

from hi_agent.contracts import TaskContract
from hi_agent.replay import ReplayEngine, load_event_envelopes_jsonl
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


def test_completed_run_replay_from_event_envelopes() -> None:
    """Replay should reconstruct a successful completed run from envelopes."""
    executor = RunExecutor(
        TaskContract(task_id="replay-001", goal="completed replay"),
        MockKernel(),
    )
    executor.execute()

    report = ReplayEngine().replay(executor.event_emitter.events)

    assert report.success is True
    assert report.task_view_count == 5
    assert report.stage_states == {
        "S1_understand": "completed",
        "S2_gather": "completed",
        "S3_build": "completed",
        "S4_synthesize": "completed",
        "S5_review": "completed",
    }


def test_failed_run_replay_from_jsonl(tmp_path) -> None:
    """Replay should load JSONL events and reconstruct a failed run."""
    executor = RunExecutor(
        TaskContract(
            task_id="replay-002",
            goal="failed replay",
            constraints=["fail_action:build_draft"],
        ),
        MockKernel(strict_mode=True),
    )
    executor.execute()

    event_path = tmp_path / "events.jsonl"
    with event_path.open("w", encoding="utf-8") as handle:
        for envelope in executor.event_emitter.events:
            handle.write(json.dumps(asdict(envelope), ensure_ascii=False) + "\n")

    loaded_events = load_event_envelopes_jsonl(event_path)
    report = ReplayEngine().replay(loaded_events)

    assert report.success is False
    assert report.task_view_count == sum(
        1 for envelope in loaded_events if envelope.event_type == "TaskViewRecorded"
    )
    assert report.stage_states["S3_build"] == "failed"
    assert report.stage_states["S1_understand"] == "completed"
