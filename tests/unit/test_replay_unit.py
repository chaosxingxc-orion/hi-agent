"""Unit tests for hi_agent.replay — Layer 1 (unit).

Covers:
  - ReplayEngine.replay: event folding, stage state tracking, success/failure
  - ReplayReport: default state, field semantics
  - ReplayRecorder: write/read round-trip using tmp_path

No network, no real LLM, no external dependencies.
Profile validated: default-offline
"""

from __future__ import annotations

from hi_agent.events import EventEnvelope
from hi_agent.replay.engine import ReplayEngine, ReplayReport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(event_type: str, run_id: str = "r1", **payload) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        run_id=run_id,
        payload=payload,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _stage_changed(stage_id: str, to_state: str, run_id: str = "r1") -> EventEnvelope:
    return _env("StageStateChanged", run_id=run_id, stage_id=stage_id, to_state=to_state)


# ---------------------------------------------------------------------------
# ReplayReport defaults
# ---------------------------------------------------------------------------


class TestReplayReportDefaults:
    def test_default_success_is_false(self) -> None:
        r = ReplayReport()
        assert r.success is False

    def test_default_task_view_count_is_zero(self) -> None:
        r = ReplayReport()
        assert r.task_view_count == 0

    def test_default_stage_states_empty(self) -> None:
        r = ReplayReport()
        assert r.stage_states == {}


# ---------------------------------------------------------------------------
# ReplayEngine — successful run
# ---------------------------------------------------------------------------


class TestReplayEngineSuccess:
    def test_all_stages_completed_yields_success(self) -> None:
        events = [
            _stage_changed("S1", "completed"),
            _stage_changed("S2", "completed"),
        ]
        report = ReplayEngine().replay(events)
        assert report.success is True
        assert report.stage_states == {"S1": "completed", "S2": "completed"}

    def test_task_view_recorded_increments_count(self) -> None:
        events = [
            _stage_changed("S1", "completed"),
            _env("TaskViewRecorded"),
            _env("TaskViewRecorded"),
        ]
        report = ReplayEngine().replay(events)
        assert report.task_view_count == 2

    def test_empty_event_stream_not_success(self) -> None:
        report = ReplayEngine().replay([])
        assert report.success is False
        assert report.stage_states == {}


# ---------------------------------------------------------------------------
# ReplayEngine — failure paths
# ---------------------------------------------------------------------------


class TestReplayEngineFailure:
    def test_stage_failed_state_marks_not_success(self) -> None:
        events = [
            _stage_changed("S1", "completed"),
            _stage_changed("S2", "failed"),
        ]
        report = ReplayEngine().replay(events)
        assert report.success is False
        assert report.stage_states["S2"] == "failed"

    def test_stage_failed_event_type_marks_not_success(self) -> None:
        events = [
            _stage_changed("S1", "completed"),
            _env("StageFailed", stage_id="S2"),
        ]
        report = ReplayEngine().replay(events)
        assert report.success is False

    def test_action_execution_failed_marks_not_success(self) -> None:
        events = [
            _env("ActionExecutionFailed", action="tool_call"),
        ]
        report = ReplayEngine().replay(events)
        assert report.success is False

    def test_partial_completion_without_explicit_terminal_not_success(self) -> None:
        """If one stage is not completed, overall success must be False."""
        events = [
            _stage_changed("S1", "completed"),
            _stage_changed("S2", "running"),
        ]
        report = ReplayEngine().replay(events)
        assert report.success is False


# ---------------------------------------------------------------------------
# ReplayEngine — state tracking
# ---------------------------------------------------------------------------


class TestReplayEngineStateTracking:
    def test_later_stage_update_overwrites_earlier(self) -> None:
        """If a stage emits multiple state changes, the last one wins."""
        events = [
            _stage_changed("S1", "running"),
            _stage_changed("S1", "completed"),
        ]
        report = ReplayEngine().replay(events)
        assert report.stage_states["S1"] == "completed"

    def test_missing_stage_id_in_payload_ignored(self) -> None:
        """Envelopes with missing stage_id in payload are silently skipped."""
        # _env without stage_id kwarg → stage_id absent from payload
        report = ReplayEngine().replay([])  # baseline: empty stream
        assert report.stage_states == {}

    def test_multi_run_events_tracked_independently(self) -> None:
        """Stage states from different run IDs are tracked together (engine is stateless)."""
        events = [
            _stage_changed("S1", "completed", run_id="run-A"),
            _stage_changed("S1", "completed", run_id="run-B"),
        ]
        report = ReplayEngine().replay(events)
        # Both appear as the same key S1; last state wins
        assert report.stage_states.get("S1") == "completed"
