"""Track B: research posture wires all durable backends."""
import pytest


def test_build_durable_backends_research_posture(tmp_path):
    """All 10 backends are built with file-backed paths under research posture."""
    from hi_agent.config.posture import Posture
    from hi_agent.server._durable_backends import build_durable_backends

    backends = build_durable_backends(str(tmp_path), Posture.RESEARCH)
    from hi_agent.evolve.feedback_store import FeedbackStore
    from hi_agent.management.gate_store import SQLiteGateStore
    from hi_agent.route_engine.decision_audit_store import SqliteDecisionAuditStore
    from hi_agent.server.event_store import SQLiteEventStore
    from hi_agent.server.idempotency import IdempotencyStore
    from hi_agent.server.run_queue import RunQueue
    from hi_agent.server.run_store import SQLiteRunStore
    from hi_agent.server.team_run_registry import TeamRunRegistry

    assert isinstance(backends["run_queue"], RunQueue)
    assert isinstance(backends["team_run_registry"], TeamRunRegistry)
    assert isinstance(backends["event_store"], SQLiteEventStore)
    assert isinstance(backends["decision_audit_store"], SqliteDecisionAuditStore)
    assert isinstance(backends["gate_store"], SQLiteGateStore)
    assert isinstance(backends["feedback_store"], FeedbackStore)
    assert isinstance(backends["run_store"], SQLiteRunStore)
    assert isinstance(backends["idempotency_store"], IdempotencyStore)

    # All file-backed (not :memory:)
    rq_path = backends["run_queue"].db_path
    assert rq_path != ":memory:" and rq_path.endswith(".sqlite")


def test_build_durable_backends_dev_posture_no_data_dir():
    """Dev posture with no data_dir uses :memory: (no error)."""
    from hi_agent.config.posture import Posture
    from hi_agent.server._durable_backends import build_durable_backends

    backends = build_durable_backends(None, Posture.DEV)
    # Should not raise; stores default to :memory: or equivalent
    assert backends["run_store"] is not None


def test_build_durable_backends_research_posture_no_data_dir_raises():
    """Research posture without data_dir raises RuntimeError."""
    from hi_agent.config.posture import Posture
    from hi_agent.server._durable_backends import build_durable_backends

    with pytest.raises(RuntimeError, match="research/prod posture requires"):
        build_durable_backends(None, Posture.RESEARCH)


def test_event_bus_set_event_store(tmp_path):
    """EventBus.set_event_store injects a durable store."""
    from hi_agent.server.event_bus import EventBus
    from hi_agent.server.event_store import SQLiteEventStore

    store = SQLiteEventStore(db_path=str(tmp_path / "events.db"))
    bus = EventBus()
    assert bus._event_store is None
    bus.set_event_store(store)
    assert bus._event_store is store
