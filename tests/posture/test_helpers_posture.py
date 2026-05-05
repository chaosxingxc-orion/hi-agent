"""Posture coverage for posture-aware helper functions.

The W21-AX-D `check_posture_coverage` gate (Rule 11) requires every
posture-conditional callsite in `hi_agent/` to be exercised by a test
with a `posture` parametrize key. The functions below are
private/helper sites that prior to W35 were exercised only indirectly
through their callers' tests; W35-T1B's `_validate_spine` consolidation
in `hi_agent/contracts/requests.py` exposed the indirection gap to the
gate.

These tests give each helper a direct parametrized test under both
`dev` and `research` postures so the gate sees explicit coverage by
function name. Behavioural depth is intentionally minimal — the
helpers' real semantics are validated by the per-class tests
(test_requests_posture.py / test_artifacts_posture.py / etc.).
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__validate_spine(monkeypatch, posture_name) -> None:
    """`hi_agent.contracts.requests._validate_spine` posture parity.

    Under research/prod the helper raises SpineCompletenessError when a
    spine field is empty; under dev it logs WARNING and proceeds.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)

    from hi_agent.contracts.reasoning import SpineCompletenessError
    from hi_agent.contracts.requests import _validate_spine

    if posture_name in ("research", "prod"):
        with pytest.raises(SpineCompletenessError):
            _validate_spine(
                obj_name="StubRequest",
                fields={"tenant_id": "", "run_id": "r1"},
            )
    else:
        # dev: should not raise
        _validate_spine(
            obj_name="StubRequest",
            fields={"tenant_id": "", "run_id": "r1"},
        )


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__resolve_tenant_for_read(monkeypatch, posture_name) -> None:
    """`hi_agent.knowledge.wiki._resolve_tenant_for_read` posture parity.

    Under research/prod, missing tenant_id raises; under dev, falls
    back to the legacy bucket. Helper is a @staticmethod so we call it
    without instantiating the wiki.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.knowledge.wiki import KnowledgeWiki

    if posture_name in ("research", "prod"):
        with pytest.raises(ValueError):
            KnowledgeWiki._resolve_tenant_for_read(tenant_id=None, op="read")
    else:
        out = KnowledgeWiki._resolve_tenant_for_read(tenant_id=None, op="read")
        assert isinstance(out, str)


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__resolve_tenant_for_write(monkeypatch, posture_name) -> None:
    """`hi_agent.knowledge.wiki._resolve_tenant_for_write` posture parity."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.knowledge.wiki import KnowledgeWiki

    if posture_name in ("research", "prod"):
        with pytest.raises(ValueError):
            KnowledgeWiki._resolve_tenant_for_write(tenant_id=None, op="write")
    else:
        out = KnowledgeWiki._resolve_tenant_for_write(tenant_id=None, op="write")
        assert isinstance(out, str)


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test_max_sequence(monkeypatch, posture_name, tmp_path) -> None:
    """`hi_agent.server.event_store.SQLiteEventStore.max_sequence` posture parity.

    Under research/prod the empty-tenant_id call raises; under dev it
    falls back to the global max sequence.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.server.event_store import SQLiteEventStore

    store = SQLiteEventStore(db_path=str(tmp_path / "events.db"))
    try:
        if posture_name in ("research", "prod"):
            with pytest.raises(ValueError):
                store.max_sequence(run_id="r1", tenant_id="")
        else:
            seq = store.max_sequence(run_id="r1", tenant_id="")
            assert isinstance(seq, int)
    finally:
        store.close()


@pytest.mark.parametrize("posture_name", ["dev", "research", "prod"])
def test__check_run_store_tenant_scope(monkeypatch, posture_name) -> None:
    """`hi_agent.server.run_store._check_run_store_tenant_scope` posture parity.

    Under research/prod the empty-tenant_id call raises TenantScopeError;
    under dev it logs and returns.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    # The store-level helper raises its OWN TenantScopeError class
    # (hi_agent.server.run_store.TenantScopeError, a ValueError subclass),
    # not the contracts one — they coexist by design.
    from hi_agent.server.run_store import (
        TenantScopeError,
        _check_run_store_tenant_scope,
    )

    if posture_name in ("research", "prod"):
        with pytest.raises(TenantScopeError):
            _check_run_store_tenant_scope(workspace=None, method="probe")
    else:
        # dev: returns "" (or None) without raising
        result = _check_run_store_tenant_scope(workspace=None, method="probe")
        assert result is None or isinstance(result, str)
