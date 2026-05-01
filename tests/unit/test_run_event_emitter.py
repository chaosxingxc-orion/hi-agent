"""Unit tests for RunEventEmitter (C8: 12 typed run lifecycle events)."""

from __future__ import annotations

from hi_agent.observability.event_emitter import (
    RUN_EVENT_METRIC_NAMES,
    RunEventEmitter,
    clear_run_events,
    get_run_events,
)


def _emitter(run_id: str = "run-test-1") -> RunEventEmitter:
    return RunEventEmitter(run_id=run_id, tenant_id="t1")


class TestMetricNames:
    def test_exactly_12_metric_names(self):
        assert len(RUN_EVENT_METRIC_NAMES) == 12

    def test_all_names_prefixed(self):
        for name in RUN_EVENT_METRIC_NAMES:
            assert name.startswith("hi_agent_"), name

    def test_all_names_suffixed_total(self):
        for name in RUN_EVENT_METRIC_NAMES:
            assert name.endswith("_total"), name


class TestRunLevelEvents:
    def setup_method(self):
        clear_run_events("run-test-1")

    def test_record_run_submitted_appends_event(self):
        emitter = _emitter()
        emitter.record_run_submitted()
        events = get_run_events("run-test-1")
        assert any(e["type"] == "run_submitted" for e in events)

    def test_record_run_started_appends_event(self):
        emitter = _emitter()
        emitter.record_run_started()
        events = get_run_events("run-test-1")
        assert any(e["type"] == "run_started" for e in events)

    def test_record_run_completed_includes_duration(self):
        emitter = _emitter()
        emitter.record_run_completed(duration_ms=1234.5)
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "run_completed")
        assert evt["duration_ms"] == 1234.5

    def test_record_run_failed_includes_reason(self):
        emitter = _emitter()
        emitter.record_run_failed(reason="timeout")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "run_failed")
        assert evt["reason"] == "timeout"

    def test_record_run_cancelled_includes_reason(self):
        emitter = _emitter()
        emitter.record_run_cancelled(reason="client_request")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "run_cancelled")
        assert evt["reason"] == "client_request"

    def test_record_run_resumed_includes_from_stage(self):
        emitter = _emitter()
        emitter.record_run_resumed(from_stage="gather")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "run_resumed")
        assert evt["from_stage"] == "gather"


class TestStageLevelEvents:
    def setup_method(self):
        clear_run_events("run-test-1")

    def test_record_stage_started_appends_stage_id(self):
        emitter = _emitter()
        emitter.record_stage_started(stage_id="synthesis")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "stage_started")
        assert evt["stage_id"] == "synthesis"

    def test_record_stage_completed_includes_duration(self):
        emitter = _emitter()
        emitter.record_stage_completed(stage_id="synthesis", duration_ms=500.0)
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "stage_completed")
        assert evt["stage_id"] == "synthesis"
        assert evt["duration_ms"] == 500.0

    def test_record_stage_failed_includes_reason(self):
        emitter = _emitter()
        emitter.record_stage_failed(stage_id="gather", reason="llm_error")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "stage_failed")
        assert evt["stage_id"] == "gather"
        assert evt["reason"] == "llm_error"


class TestArtifactAndEvolutionEvents:
    def setup_method(self):
        clear_run_events("run-test-1")

    def test_record_artifact_created_includes_type(self):
        emitter = _emitter()
        emitter.record_artifact_created(artifact_type="code")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "artifact_created")
        assert evt["artifact_type"] == "code"

    def test_record_experiment_posted_includes_experiment_id(self):
        emitter = _emitter()
        emitter.record_experiment_posted(experiment_id="exp-42")
        events = get_run_events("run-test-1")
        evt = next(e for e in events if e["type"] == "experiment_posted")
        assert evt["experiment_id"] == "exp-42"

    def test_record_feedback_submitted_appends_event(self):
        emitter = _emitter()
        emitter.record_feedback_submitted()
        events = get_run_events("run-test-1")
        assert any(e["type"] == "feedback_submitted" for e in events)


class TestTenantAttributionAndIsolation:
    def setup_method(self):
        clear_run_events("run-a")
        clear_run_events("run-b")

    def test_tenant_id_in_event_payload(self):
        emitter = RunEventEmitter(run_id="run-a", tenant_id="tenant-xyz")
        emitter.record_run_submitted()
        events = get_run_events("run-a")
        assert events[0]["tenant_id"] == "tenant-xyz"

    def test_events_isolated_per_run(self):
        RunEventEmitter(run_id="run-a", tenant_id="t1").record_run_submitted()
        RunEventEmitter(run_id="run-b", tenant_id="t2").record_run_started()
        assert all(e["type"] == "run_submitted" for e in get_run_events("run-a"))
        assert all(e["type"] == "run_started" for e in get_run_events("run-b"))

    def test_clear_run_events_removes_all(self):
        emitter = _emitter("run-a")
        emitter.record_run_submitted()
        clear_run_events("run-a")
        assert get_run_events("run-a") == []

    def test_get_run_events_returns_copy(self):
        emitter = _emitter("run-a")
        emitter.record_run_submitted()
        events1 = get_run_events("run-a")
        events1.clear()
        assert len(get_run_events("run-a")) == 1

    def test_events_have_timestamp(self):
        emitter = _emitter("run-a")
        emitter.record_run_submitted()
        events = get_run_events("run-a")
        assert events[0]["ts"] > 0

    def test_all_12_event_types_covered(self):
        run_id = "run-all"
        clear_run_events(run_id)
        emitter = RunEventEmitter(run_id=run_id, tenant_id="t1")
        emitter.record_run_submitted()
        emitter.record_run_started()
        emitter.record_run_completed(duration_ms=1.0)
        emitter.record_run_failed(reason="test")
        emitter.record_run_cancelled(reason="test")
        emitter.record_run_resumed(from_stage="s1")
        emitter.record_stage_started(stage_id="s1")
        emitter.record_stage_completed(stage_id="s1", duration_ms=1.0)
        emitter.record_stage_failed(stage_id="s1", reason="test")
        emitter.record_artifact_created(artifact_type="code")
        emitter.record_experiment_posted(experiment_id="e1")
        emitter.record_feedback_submitted()
        event_types = {e["type"] for e in get_run_events(run_id)}
        assert len(event_types) == 12
