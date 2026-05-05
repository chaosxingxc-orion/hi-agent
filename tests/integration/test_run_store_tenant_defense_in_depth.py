"""W34+ T1a: SQLiteRunStore mutation-method tenant defense-in-depth.

Mirror of W33-D.2 RunQueue tenant-scoping coverage. Every mutating method
on ``SQLiteRunStore`` accepts an optional ``workspace`` (tenant_id) parameter
that is REQUIRED under research/prod posture and warns under dev. Without
this guard, ``mark_cancelled``/``mark_complete``/``mark_failed``/
``mark_running``/``is_cancelled``/``delete`` could mutate or read another
tenant's run by run_id alone.

Layer: integration (Rule 4 Layer 2). Each test exercises the real
SQLiteRunStore via tmp_path; no mocks on the subject under test.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from hi_agent.server.run_store import RunRecord, SQLiteRunStore, TenantScopeError


@pytest.fixture
def store(tmp_path: Path):
    """Build a fresh SQLiteRunStore at a tmp path."""
    db = tmp_path / "runs.db"
    s = SQLiteRunStore(db)
    yield s
    s.close()


def _record(run_id: str, tenant_id: str) -> RunRecord:
    now = time.time()
    return RunRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=now,
        updated_at=now,
        user_id="user-1",
        session_id="sess-1",
    )


@pytest.fixture
def _research_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")


@pytest.fixture
def _dev_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


# ---------------------------------------------------------------------------
# mark_cancelled
# ---------------------------------------------------------------------------

def test_mark_cancelled_requires_workspace_under_research(
    store: SQLiteRunStore, _research_posture: None
) -> None:
    rec = _record("run-A", "tenant-A")
    store.upsert(rec)
    with pytest.raises(TenantScopeError):
        store.mark_cancelled("run-A")


def test_mark_cancelled_with_workspace_research_succeeds(
    store: SQLiteRunStore, _research_posture: None
) -> None:
    rec = _record("run-A", "tenant-A")
    store.upsert(rec)
    store.mark_cancelled("run-A", workspace="tenant-A")
    assert store.is_cancelled("run-A", workspace="tenant-A") is True


def test_mark_cancelled_cross_tenant_research_no_op(
    store: SQLiteRunStore, _research_posture: None
) -> None:
    """Tenant B cannot cancel tenant A's run by run_id alone."""
    rec = _record("run-A", "tenant-A")
    store.upsert(rec)
    # Tenant B passes its own tenant_id; the WHERE clause matches no row.
    store.mark_cancelled("run-A", workspace="tenant-B")
    # Verify tenant A's run is still uncancelled.
    assert store.is_cancelled("run-A", workspace="tenant-A") is False


def test_mark_cancelled_dev_warns_no_workspace(
    store: SQLiteRunStore,
    _dev_posture: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    caplog.set_level(logging.WARNING, logger="hi_agent.server.run_store")
    rec = _record("run-A", "tenant-A")
    store.upsert(rec)
    store.mark_cancelled("run-A")  # no workspace — dev allows
    assert any("workspace=None" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# mark_complete + mark_failed + mark_running + is_cancelled + delete
# (parametrise over the 5 methods that already had optional workspace param)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,args",
    [
        ("mark_complete", ("result-string",)),
        ("mark_failed", ("error-string",)),
        ("mark_running", ()),
        ("is_cancelled", ()),
        ("delete", ()),
    ],
)
def test_mutation_method_requires_workspace_under_research(
    store: SQLiteRunStore,
    _research_posture: None,
    method: str,
    args: tuple,
) -> None:
    rec = _record("run-X", "tenant-X")
    store.upsert(rec)
    fn = getattr(store, method)
    with pytest.raises(TenantScopeError):
        fn("run-X", *args)


@pytest.mark.parametrize(
    "method,args",
    [
        ("mark_complete", ("result-string",)),
        ("mark_failed", ("error-string",)),
        ("mark_running", ()),
        ("delete", ()),
    ],
)
def test_mutation_method_workspace_research_succeeds(
    store: SQLiteRunStore,
    _research_posture: None,
    method: str,
    args: tuple,
) -> None:
    rec = _record("run-X", "tenant-X")
    store.upsert(rec)
    fn = getattr(store, method)
    fn("run-X", *args, workspace="tenant-X")  # no exception


def test_is_cancelled_cross_tenant_research_returns_false(
    store: SQLiteRunStore, _research_posture: None
) -> None:
    rec = _record("run-X", "tenant-X")
    store.upsert(rec)
    store.mark_cancelled("run-X", workspace="tenant-X")
    # Tenant Y queries with its own scope → row not visible → returns False.
    assert store.is_cancelled("run-X", workspace="tenant-Y") is False
    # Tenant X queries with correct scope → True.
    assert store.is_cancelled("run-X", workspace="tenant-X") is True
