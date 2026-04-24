"""Integration tests for replay/state consistency verification."""

from __future__ import annotations

import json
from dataclasses import asdict

from hi_agent.contracts import TaskContract
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.replay import verify_replay_against_files
from hi_agent.runner import RunExecutor
from hi_agent.state import RunStateStore

from tests.helpers.kernel_adapter_fixture import MockKernel


def _persist_run_artifacts(executor: RunExecutor, events_path, state_path) -> None:
    """Persist event stream JSONL and run state snapshot for verification."""
    with events_path.open("w", encoding="utf-8") as handle:
        for envelope in executor.event_emitter.events:
            handle.write(json.dumps(asdict(envelope), ensure_ascii=False) + "\n")

    snapshot = executor.state_store.get(executor.run_id)
    assert snapshot is not None
    state_path.write_text(
        json.dumps(
            {executor.run_id: snapshot.to_dict()},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_replay_state_verify_match_passes(tmp_path) -> None:
    """Verification should pass when replay report matches run state snapshot."""
    store = RunStateStore(file_path=tmp_path / "state.json")
    executor = RunExecutor(
        TaskContract(task_id="verify-001", goal="verify match"),
        MockKernel(strict_mode=True),
        state_store=store,
        raw_memory=RawMemoryStore(),
    )
    executor.execute()

    events_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    _persist_run_artifacts(executor, events_path, state_path)

    report = verify_replay_against_files(
        event_file=events_path,
        state_file=state_path,
        run_id=executor.run_id,
    )

    assert report.match is True
    assert report.mismatches == []


def test_replay_state_verify_result_mismatch(tmp_path) -> None:
    """Verification should fail when run result conflicts with replay success."""
    store = RunStateStore(file_path=tmp_path / "state.json")
    executor = RunExecutor(
        TaskContract(task_id="verify-002", goal="verify result mismatch"),
        MockKernel(strict_mode=True),
        state_store=store,
        raw_memory=RawMemoryStore(),
    )
    executor.execute()

    events_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    _persist_run_artifacts(executor, events_path, state_path)

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload[executor.run_id]["result"] = "failed"
    state_path.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = verify_replay_against_files(
        event_file=events_path,
        state_file=state_path,
        run_id=executor.run_id,
    )

    assert report.match is False
    assert any("result/success mismatch" in message for message in report.mismatches)


def test_replay_state_verify_task_view_mismatch(tmp_path) -> None:
    """Verification should fail on large task view count drift under weak mode."""
    store = RunStateStore(file_path=tmp_path / "state.json")
    executor = RunExecutor(
        TaskContract(task_id="verify-003", goal="verify task view mismatch"),
        MockKernel(strict_mode=True),
        state_store=store,
        raw_memory=RawMemoryStore(),
    )
    executor.execute()

    events_path = tmp_path / "events.jsonl"
    state_path = tmp_path / "state.json"
    _persist_run_artifacts(executor, events_path, state_path)

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload[executor.run_id]["task_views_count"] = 0
    state_path.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    report = verify_replay_against_files(
        event_file=events_path,
        state_file=state_path,
        run_id=executor.run_id,
        weak_task_view=True,
    )

    assert report.match is False
    assert any("task_view_count mismatch" in message for message in report.mismatches)
