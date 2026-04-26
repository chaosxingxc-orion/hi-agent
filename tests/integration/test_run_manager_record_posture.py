"""Track W2-E.3: RunManager refuses ``__legacy__`` upserts under strict posture.

Audit found that ``RunManager.create_run`` upserted ``RunRecord(... user_id=
workspace.user_id if workspace else "__legacy__", ...)`` unconditionally.
Under research/prod the durable run_store is default-on, so the legacy
sentinel would silently pollute cross-run attribution.

This test mirrors the W2-Spine-2 trip-wire pattern from
``TeamRunRegistry.register``:

- research posture + workspace=None → ``ValueError`` (fail-closed).
- dev posture + workspace=None → upsert proceeds with ``__legacy__`` sentinel
  (back-compat for existing dev fixtures / legacy tests).

Layer 2 — Integration: real ``SQLiteRunStore`` on a tmp file, real
``RunManager``.  No MagicMock on the subsystem under test.
"""

from __future__ import annotations

import pytest
from hi_agent.server.run_manager import RunManager
from hi_agent.server.run_store import SQLiteRunStore
from hi_agent.server.tenant_context import TenantContext

pytestmark = pytest.mark.integration


@pytest.fixture()
def run_store(tmp_path):
    return SQLiteRunStore(db_path=str(tmp_path / "runs.sqlite3"))


@pytest.fixture()
def manager(run_store):
    return RunManager(max_concurrent=1, queue_size=4, run_store=run_store)


# ---------------------------------------------------------------------------
# research posture: fail-closed
# ---------------------------------------------------------------------------


def test_research_posture_rejects_workspaceless_upsert(monkeypatch, manager):
    """Under research posture, calling create_run without workspace raises."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    with pytest.raises(ValueError, match="authenticated workspace"):
        manager.create_run({"goal": "x", "task_id": "t-strict-1"}, workspace=None)


def test_prod_posture_rejects_workspaceless_upsert(monkeypatch, manager):
    """Under prod posture, same fail-closed behaviour."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    with pytest.raises(ValueError, match="authenticated workspace"):
        manager.create_run({"goal": "x", "task_id": "t-strict-2"}, workspace=None)


def test_research_posture_with_workspace_persists_real_identity(
    monkeypatch, manager, run_store
):
    """Under research posture, workspace identity is persisted (no sentinel)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    ctx = TenantContext(tenant_id="t1", user_id="u1", session_id="s1")
    run = manager.create_run(
        {"goal": "x", "task_id": "t-strict-3", "project_id": "proj-X"},
        workspace=ctx,
    )
    record = run_store.get(run.run_id)
    assert record is not None
    assert record.user_id == "u1"
    assert record.session_id == "s1"
    assert record.project_id == "proj-X"


# ---------------------------------------------------------------------------
# dev posture: permissive (back-compat)
# ---------------------------------------------------------------------------


def test_dev_posture_workspaceless_upsert_uses_legacy_sentinel(
    monkeypatch, manager, run_store
):
    """Under dev posture, workspace=None still upserts using the sentinel."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    run = manager.create_run({"goal": "x", "task_id": "t-dev-1"}, workspace=None)
    record = run_store.get(run.run_id)
    assert record is not None
    assert record.user_id == "__legacy__"
    assert record.session_id == "__legacy__"
