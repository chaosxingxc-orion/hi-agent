"""End-to-end restart replay consistency integration tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from hi_agent.contracts import TaskContract
from hi_agent.replay import load_event_envelopes_jsonl, verify_replay_against_files
from hi_agent.runner import RunExecutor
from hi_agent.state import RunStateStore

from tests.helpers.kernel_adapter_fixture import MockKernel


def _persist_events(executor: RunExecutor, events_path: Path) -> None:
    """Persist emitted events to JSONL for replay verification."""
    with events_path.open("w", encoding="utf-8") as handle:
        for envelope in executor.event_emitter.events:
            handle.write(json.dumps(asdict(envelope), ensure_ascii=False) + "\n")


def test_e2e_restart_replay_consistency_match(tmp_path: Path) -> None:
    """After restart, reconstructed file-backed stores should verify as consistent."""
    state_path = tmp_path / "run_state.json"
    events_path = tmp_path / "events.jsonl"
    contract = TaskContract(task_id="e2e-restart-001", goal="restart replay consistency")

    first_process_store = RunStateStore(file_path=state_path)
    executor = RunExecutor(contract, MockKernel(strict_mode=True), state_store=first_process_store)
    result = executor.execute()
    _persist_events(executor, events_path)

    assert result == "completed"

    # Simulate process restart: reconstruct both persisted stores from files.
    restarted_state_store = RunStateStore(file_path=state_path)
    restored_snapshot = restarted_state_store.get(executor.run_id)
    restored_events = load_event_envelopes_jsonl(events_path)

    assert restored_snapshot is not None
    assert restored_events
    assert all(event.run_id == executor.run_id for event in restored_events)

    report = verify_replay_against_files(
        event_file=events_path,
        state_file=state_path,
        run_id=executor.run_id,
    )

    assert report.match is True
    assert report.mismatches == []


def test_e2e_restart_replay_consistency_detects_tampered_current_stage(
    tmp_path: Path,
) -> None:
    """Verification should fail when persisted current_stage is tampered after restart."""
    state_path = tmp_path / "run_state.json"
    events_path = tmp_path / "events.jsonl"
    contract = TaskContract(task_id="e2e-restart-002", goal="detect tampered stage")

    first_process_store = RunStateStore(file_path=state_path)
    executor = RunExecutor(contract, MockKernel(strict_mode=True), state_store=first_process_store)
    result = executor.execute()
    _persist_events(executor, events_path)

    assert result == "completed"

    # Simulate persisted snapshot tampering before restart verification.
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload[executor.run_id]["current_stage"] = "S3_build"
    state_path.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Simulate restart by reconstructing file-backed state store after tampering.
    restarted_state_store = RunStateStore(file_path=state_path)
    restored_snapshot = restarted_state_store.get(executor.run_id)
    assert restored_snapshot is not None
    assert restored_snapshot.current_stage == "S3_build"

    report = verify_replay_against_files(
        event_file=events_path,
        state_file=state_path,
        run_id=executor.run_id,
    )

    assert report.match is False
    assert any("current_stage mismatch" in mismatch for mismatch in report.mismatches)
