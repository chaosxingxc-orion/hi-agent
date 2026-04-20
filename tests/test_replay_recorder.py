"""Tests for ReplayRecorder, ReplayEngine, and verify."""

from __future__ import annotations

from hi_agent.events.envelope import EventEnvelope
from hi_agent.replay.engine import ReplayEngine
from hi_agent.replay.io import ReplayRecorder, load_event_envelopes_jsonl


def _make_envelope(
    event_type: str = "StageStateChanged",
    run_id: str = "run-1",
    payload: dict | None = None,
    timestamp: str = "2026-01-01T00:00:00Z",
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        run_id=run_id,
        payload=payload or {},
        timestamp=timestamp,
    )


class TestReplayRecorder:
    """ReplayRecorder tests."""

    def test_record_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "events.jsonl"
        recorder = ReplayRecorder(path)
        env1 = _make_envelope("StageStateChanged", payload={"stage_id": "S1", "to_state": "completed"})
        env2 = _make_envelope("TaskViewRecorded", payload={"tokens": 100})
        recorder.record(env1)
        recorder.record(env2)
        recorder.close()

        loaded = load_event_envelopes_jsonl(path)
        assert len(loaded) == 2
        assert loaded[0].event_type == "StageStateChanged"
        assert loaded[1].event_type == "TaskViewRecorded"

    def test_context_manager(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with ReplayRecorder(path) as recorder:
            recorder.record(_make_envelope())
        loaded = load_event_envelopes_jsonl(path)
        assert len(loaded) == 1

    def test_parent_dir_creation(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "events.jsonl"
        recorder = ReplayRecorder(deep_path)
        recorder.record(_make_envelope())
        recorder.close()
        assert deep_path.exists()

    def test_empty_stream(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text("")
        loaded = load_event_envelopes_jsonl(path)
        assert loaded == []

    def test_mixed_stages(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with ReplayRecorder(path) as rec:
            rec.record(_make_envelope("StageStateChanged", payload={"stage_id": "S1", "to_state": "completed"}))
            rec.record(_make_envelope("TaskViewRecorded", payload={}))
            rec.record(_make_envelope("StageStateChanged", payload={"stage_id": "S2", "to_state": "completed"}))

        loaded = load_event_envelopes_jsonl(path)
        assert len(loaded) == 3

    def test_path_property(self, tmp_path):
        path = tmp_path / "events.jsonl"
        recorder = ReplayRecorder(path)
        assert recorder.path == path
        recorder.close()


class TestReplayEngine:
    """ReplayEngine tests."""

    def test_replay_successful_stages(self):
        engine = ReplayEngine()
        events = [
            _make_envelope("StageStateChanged", payload={"stage_id": "S1", "to_state": "completed"}),
            _make_envelope("StageStateChanged", payload={"stage_id": "S2", "to_state": "completed"}),
        ]
        report = engine.replay(events)
        assert report.success is True
        assert report.stage_states == {"S1": "completed", "S2": "completed"}

    def test_replay_with_failure(self):
        engine = ReplayEngine()
        events = [
            _make_envelope("StageStateChanged", payload={"stage_id": "S1", "to_state": "completed"}),
            _make_envelope("StageStateChanged", payload={"stage_id": "S2", "to_state": "failed"}),
        ]
        report = engine.replay(events)
        assert report.success is False

    def test_task_view_count(self):
        engine = ReplayEngine()
        events = [
            _make_envelope("TaskViewRecorded"),
            _make_envelope("TaskViewRecorded"),
            _make_envelope("StageStateChanged", payload={"stage_id": "S1", "to_state": "completed"}),
        ]
        report = engine.replay(events)
        assert report.task_view_count == 2

    def test_empty_events(self):
        engine = ReplayEngine()
        report = engine.replay([])
        assert report.success is False
        assert report.stage_states == {}


class TestVerifyIntegration:
    """Integration: record -> replay -> verify."""

    def test_roundtrip_verify(self, tmp_path):
        path = tmp_path / "events.jsonl"
        with ReplayRecorder(path) as rec:
            rec.record(_make_envelope("StageStateChanged", payload={"stage_id": "S1", "to_state": "completed"}))
            rec.record(_make_envelope("StageStateChanged", payload={"stage_id": "S2", "to_state": "completed"}))
            rec.record(_make_envelope("TaskViewRecorded"))

        loaded = load_event_envelopes_jsonl(path)
        engine = ReplayEngine()
        report = engine.replay(loaded)
        assert report.success is True
        assert report.task_view_count == 1
        assert len(report.stage_states) == 2
