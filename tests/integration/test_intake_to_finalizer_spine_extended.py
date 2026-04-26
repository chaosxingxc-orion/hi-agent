"""Integration tests: end-to-end spine consistency across all 5 durable writers.

Layer 2 — Integration tests verifying that a single RunExecutionContext
propagates consistent spine (tenant_id, user_id, session_id, run_id,
project_id) through all five durable writers wired together:

1. IdempotencyStore.reserve_or_replay
2. SQLiteEventStore.append
3. TeamRunRegistry.register
4. SessionStore.create
5. ArtifactRegistry.create

Real components are used; no mocks on the subsystems under test per Rule 4.
"""

from __future__ import annotations

import pytest
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.contracts.team_runtime import TeamRun
from hi_agent.server.event_store import SQLiteEventStore, StoredEvent
from hi_agent.server.idempotency import IdempotencyStore
from hi_agent.server.session_store import SessionStore
from hi_agent.server.team_run_registry import TeamRunRegistry


@pytest.fixture(autouse=True)
def dev_posture(monkeypatch):
    """Force dev posture so ArtifactRegistry can be constructed."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


@pytest.fixture()
def exec_ctx():
    """A fully-populated RunExecutionContext used across all writers."""
    return RunExecutionContext(
        tenant_id="spine-tenant",
        user_id="spine-user",
        session_id="spine-session",
        project_id="spine-project",
        run_id="spine-run-001",
        profile_id="profile-001",
    )


@pytest.fixture()
def idempotency_store(tmp_path):
    s = IdempotencyStore(db_path=tmp_path / "idempotency.db")
    yield s
    s.close()


@pytest.fixture()
def event_store():
    s = SQLiteEventStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture()
def team_registry():
    r = TeamRunRegistry(db_path=":memory:")
    yield r
    r.close()


@pytest.fixture()
def session_store():
    s = SessionStore(db_path=":memory:")
    s.initialize()
    yield s


@pytest.fixture()
def artifact_registry():
    from hi_agent.artifacts.registry import ArtifactRegistry
    return ArtifactRegistry()


class TestAllWritersCarryConsistentSpine:
    def test_idempotency_record_carries_exec_ctx_spine(self, idempotency_store, exec_ctx):
        """Writer 1: IdempotencyStore record reflects exec_ctx spine."""
        outcome, record = idempotency_store.reserve_or_replay(
            tenant_id="overridden",
            idempotency_key="spine-key-001",
            request_hash="hash-001",
            run_id=exec_ctx.run_id,
            exec_ctx=exec_ctx,
        )
        assert outcome == "created"
        assert record.tenant_id == "spine-tenant"
        assert record.user_id == "spine-user"
        assert record.session_id == "spine-session"
        assert record.project_id == "spine-project"

    def test_stored_event_carries_exec_ctx_spine(self, event_store, exec_ctx):
        """Writer 2: StoredEvent reflects exec_ctx spine after append."""
        event = StoredEvent(
            event_id="evt-spine-001",
            run_id="original-run",
            sequence=1,
            event_type="test",
            payload_json="{}",
        )
        event_store.append(event, exec_ctx=exec_ctx)

        rows = event_store.list_since("spine-run-001", since_sequence=0)
        assert len(rows) == 1
        stored = rows[0]
        assert stored.tenant_id == "spine-tenant"
        assert stored.user_id == "spine-user"
        assert stored.session_id == "spine-session"
        assert stored.run_id == "spine-run-001"

    def test_team_run_carries_exec_ctx_spine(self, team_registry, exec_ctx):
        """Writer 3: TeamRun in registry reflects exec_ctx spine."""
        team_run = TeamRun(
            team_id="spine-team-001",
            pi_run_id=exec_ctx.run_id,
            project_id="original-project",
        )
        team_registry.register(team_run, exec_ctx=exec_ctx)

        retrieved = team_registry.get("spine-team-001")
        assert retrieved is not None
        assert retrieved.tenant_id == "spine-tenant"
        assert retrieved.user_id == "spine-user"
        assert retrieved.session_id == "spine-session"

    def test_session_carries_exec_ctx_spine(self, session_store, exec_ctx):
        """Writer 4: Session record reflects exec_ctx spine."""
        sid = session_store.create(
            tenant_id="overridden",
            user_id="overridden",
            exec_ctx=exec_ctx,
        )
        record = session_store.get(sid)
        assert record is not None
        assert record.tenant_id == "spine-tenant"
        assert record.user_id == "spine-user"

    def test_artifact_carries_exec_ctx_run_id_and_project_id(
        self, artifact_registry, exec_ctx
    ):
        """Writer 5: Artifact reflects exec_ctx run_id and project_id."""
        artifact = artifact_registry.create(exec_ctx=exec_ctx, artifact_type="spine_test")
        assert artifact.run_id == "spine-run-001"
        assert artifact.project_id == "spine-project"
        assert artifact.tenant_id == "spine-tenant"
        assert artifact.user_id == "spine-user"
        assert artifact.session_id == "spine-session"

    def test_all_five_writers_with_same_exec_ctx_produce_consistent_spine(
        self,
        idempotency_store,
        event_store,
        team_registry,
        session_store,
        artifact_registry,
        exec_ctx,
    ):
        """Smoke: all 5 writers accept the same exec_ctx without error."""
        # Writer 1
        outcome, record = idempotency_store.reserve_or_replay(
            tenant_id="t",
            idempotency_key="spine-all-001",
            request_hash="h-all",
            run_id=exec_ctx.run_id,
            exec_ctx=exec_ctx,
        )
        assert outcome == "created"

        # Writer 2
        event = StoredEvent(
            event_id="evt-all-001",
            run_id="placeholder",
            sequence=1,
            event_type="smoke",
            payload_json="{}",
        )
        event_store.append(event, exec_ctx=exec_ctx)

        # Writer 3
        team_run = TeamRun(
            team_id="team-all-001",
            pi_run_id=exec_ctx.run_id,
            project_id="",
        )
        team_registry.register(team_run, exec_ctx=exec_ctx)

        # Writer 4
        sid = session_store.create("t", "u", exec_ctx=exec_ctx)
        assert sid

        # Writer 5
        artifact = artifact_registry.create(exec_ctx=exec_ctx)
        assert artifact.run_id == exec_ctx.run_id

        # Verify spine consistency across all 5
        assert record.tenant_id == "spine-tenant"
        events = event_store.list_since(exec_ctx.run_id, since_sequence=0)
        assert events[0].tenant_id == "spine-tenant"
        team = team_registry.get("team-all-001")
        assert team.tenant_id == "spine-tenant"
        session = session_store.get(sid)
        assert session.tenant_id == "spine-tenant"
        assert artifact.tenant_id == "spine-tenant"

    def test_all_writers_backward_compat_without_exec_ctx(
        self,
        idempotency_store,
        event_store,
        team_registry,
        session_store,
        artifact_registry,
    ):
        """All writers work correctly without exec_ctx (existing callers unaffected)."""
        # Writer 1 — no exec_ctx
        outcome, record = idempotency_store.reserve_or_replay(
            tenant_id="t-compat",
            idempotency_key="compat-key",
            request_hash="h-compat",
            run_id="run-compat",
        )
        assert outcome == "created"
        assert record.tenant_id == "t-compat"

        # Writer 2 — no exec_ctx
        event = StoredEvent(
            event_id="evt-compat",
            run_id="run-compat",
            sequence=1,
            event_type="compat",
            payload_json="{}",
            tenant_id="t-compat",
        )
        event_store.append(event)
        rows = event_store.list_since("run-compat", since_sequence=0)
        assert rows[0].tenant_id == "t-compat"

        # Writer 3 — no exec_ctx
        team_run = TeamRun(
            team_id="team-compat",
            pi_run_id="pi-compat",
            project_id="p-compat",
        )
        team_registry.register(team_run)
        assert team_registry.get("team-compat") is not None

        # Writer 4 — no exec_ctx
        sid = session_store.create("t-compat", "u-compat")
        assert session_store.get(sid) is not None

        # Writer 5 — no exec_ctx
        artifact = artifact_registry.create(artifact_type="compat")
        assert artifact.artifact_type == "compat"
