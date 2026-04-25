"""Track A: validation runs before any mutation (no orphan rows on failed validation)."""
import pytest


def test_create_run_rejects_missing_project_id_before_creating_run(monkeypatch, tmp_path):
    """Research posture: project_id missing → ValidationError before run is created."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    from hi_agent.config.posture import Posture
    from hi_agent.server._route_helpers import ValidationError, validate_run_request_or_raise

    posture = Posture.RESEARCH
    ctx_mock = type("Ctx", (), {"tenant_id": "t1", "user_id": "u1", "session_id": "s1"})()

    body = {"goal": "do something"}  # missing project_id
    with pytest.raises(ValidationError) as exc_info:
        validate_run_request_or_raise(body, ctx_mock, posture)
    assert "project_id" in str(exc_info.value)


def test_create_run_rejects_missing_goal():
    """Missing goal → ValidationError before create_run."""
    from hi_agent.config.posture import Posture
    from hi_agent.server._route_helpers import ValidationError, validate_run_request_or_raise

    ctx_mock = type("Ctx", (), {"tenant_id": "t1", "user_id": "u1", "session_id": "s1"})()
    with pytest.raises(ValidationError) as exc_info:
        validate_run_request_or_raise({}, ctx_mock, Posture.DEV)
    assert "goal" in str(exc_info.value)


def test_idempotency_release_removes_pending(tmp_path):
    """release() removes pending slots, not completed ones."""
    from hi_agent.server.idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=str(tmp_path / "idem.db"))
    store.reserve_or_replay("t1", "key1", "hash1", "run1")
    # Confirm it's there
    row = store._conn.execute(
        "SELECT status FROM idempotency_records WHERE tenant_id='t1' AND idempotency_key='key1'"
    ).fetchone()
    assert row[0] == "pending"

    store.release("t1", "key1")
    row = store._conn.execute(
        "SELECT status FROM idempotency_records WHERE tenant_id='t1' AND idempotency_key='key1'"
    ).fetchone()
    assert row is None  # deleted


def test_idempotency_release_does_not_delete_completed(tmp_path):
    """release() only deletes pending records, not completed ones."""
    from hi_agent.server.idempotency import IdempotencyStore

    store = IdempotencyStore(db_path=str(tmp_path / "idem.db"))
    store.reserve_or_replay("t1", "key1", "hash1", "run1")
    store.mark_complete("t1", "key1", '{"status": "done"}', "succeeded")

    # Completed record should NOT be deleted
    store.release("t1", "key1")
    row = store._conn.execute(
        "SELECT status FROM idempotency_records WHERE tenant_id='t1' AND idempotency_key='key1'"
    ).fetchone()
    assert row is not None  # still present (completed, not deleted)
    assert row[0] == "succeeded"
