"""Replay and run state consistency verification helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hi_agent.replay.engine import ReplayEngine, ReplayReport
from hi_agent.replay.io import load_event_envelopes_jsonl
from hi_agent.run_state_store import RunStateSnapshot, RunStateStore


@dataclass(slots=True)
class VerificationReport:
    """Consistency check report between replay and persisted run state."""

    match: bool
    mismatches: list[str] = field(default_factory=list)


def verify_replay_against_snapshot(
    replay_report: ReplayReport,
    snapshot: RunStateSnapshot,
    *,
    weak_task_view: bool = True,
) -> VerificationReport:
    """Verify replay report and run-state snapshot consistency."""
    mismatches: list[str] = []

    replay_success = replay_report.success
    snapshot_success = _snapshot_result_to_success(snapshot.result)
    if snapshot_success is None:
        mismatches.append(
            f"result/success mismatch: unsupported snapshot result={snapshot.result!r}"
        )
    elif replay_success != snapshot_success:
        mismatches.append(
            "result/success mismatch: "
            f"replay.success={replay_success}, snapshot.result={snapshot.result!r}"
        )

    terminal_stage = _derive_terminal_stage(replay_report)
    if terminal_stage is None:
        mismatches.append("current_stage mismatch: replay has no terminal stage")
    elif snapshot.current_stage != terminal_stage:
        mismatches.append(
            "current_stage mismatch: "
            f"replay.terminal_stage={terminal_stage!r}, "
            f"snapshot.current_stage={snapshot.current_stage!r}"
        )

    task_view_delta = abs(replay_report.task_view_count - snapshot.task_views_count)
    if weak_task_view:
        if task_view_delta > 1:
            mismatches.append(
                "task_view_count mismatch (weak): "
                f"replay.task_view_count={replay_report.task_view_count}, "
                f"snapshot.task_views_count={snapshot.task_views_count}"
            )
    elif replay_report.task_view_count != snapshot.task_views_count:
        mismatches.append(
            "task_view_count mismatch: "
            f"replay.task_view_count={replay_report.task_view_count}, "
            f"snapshot.task_views_count={snapshot.task_views_count}"
        )

    return VerificationReport(match=not mismatches, mismatches=mismatches)


def verify_replay_against_files(
    *,
    event_file: str | Path,
    state_file: str | Path,
    run_id: str | None = None,
    weak_task_view: bool = True,
) -> VerificationReport:
    """Load replay/state artifacts from files and run consistency verification."""
    events = load_event_envelopes_jsonl(event_file)
    if not events:
        return VerificationReport(match=False, mismatches=["event stream is empty"])

    selected_run_id = run_id or _infer_single_run_id(events)
    if selected_run_id is None:
        return VerificationReport(
            match=False,
            mismatches=["multiple run_id values found in event stream; pass run_id explicitly"],
        )

    run_events = [event for event in events if event.run_id == selected_run_id]
    if not run_events:
        return VerificationReport(
            match=False,
            mismatches=[f"no events found for run_id={selected_run_id!r}"],
        )

    snapshot = RunStateStore(file_path=state_file).get(selected_run_id)
    if snapshot is None:
        return VerificationReport(
            match=False,
            mismatches=[f"no run-state snapshot found for run_id={selected_run_id!r}"],
        )

    replay_report = ReplayEngine().replay(run_events)
    return verify_replay_against_snapshot(
        replay_report,
        snapshot,
        weak_task_view=weak_task_view,
    )


def _snapshot_result_to_success(result: str | None) -> bool | None:
    """Map persisted run result to success flag."""
    if result == "completed":
        return True
    if result == "failed":
        return False
    return None


def _derive_terminal_stage(replay_report: ReplayReport) -> str | None:
    """Derive terminal stage from replayed stage states."""
    if not replay_report.stage_states:
        return None
    for stage_id, stage_state in replay_report.stage_states.items():
        if stage_state == "failed":
            return stage_id
    return next(reversed(replay_report.stage_states))


def _infer_single_run_id(events) -> str | None:
    """Infer run ID when event stream contains exactly one run."""
    run_ids = {event.run_id for event in events}
    if len(run_ids) != 1:
        return None
    return next(iter(run_ids))
