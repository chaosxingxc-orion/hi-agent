"""W34+ T2a: posture-aware __post_init__ on the durable trio.

RunRecord, StoredEvent, ManagedRun all carry Rule 12 spine fields. The W33-F
work landed the storage schema; W34+ T2a closes the construction-site gap by
adding posture-aware __post_init__ validation mirroring the W34-F.3
ReasoningTrace pattern.

Layer: unit (Rule 4 Layer 1).
"""
from __future__ import annotations

import time

import pytest

from hi_agent.server.event_store import StoredEvent
from hi_agent.server.run_manager import ManagedRun
from hi_agent.server.run_store import RunRecord


@pytest.fixture
def _research_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")


@pytest.fixture
def _dev_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


# --- RunRecord -------------------------------------------------------------

def _full_run_record(**overrides) -> dict:
    base = dict(
        run_id="run-1",
        tenant_id="tenant-A",
        task_contract_json="{}",
        status="queued",
        priority=5,
        attempt_count=0,
        cancellation_flag=False,
        result_summary="",
        error_summary="",
        created_at=time.time(),
        updated_at=time.time(),
    )
    base.update(overrides)
    return base


def test_run_record_research_empty_run_id_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="run_id"):
        RunRecord(**_full_run_record(run_id=""))


def test_run_record_research_empty_tenant_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        RunRecord(**_full_run_record(tenant_id=""))


def test_run_record_research_full_spine_succeeds(_research_posture: None) -> None:
    rec = RunRecord(**_full_run_record())
    assert rec.run_id == "run-1"
    assert rec.tenant_id == "tenant-A"


def test_run_record_dev_warns_not_raises(
    _dev_posture: None, caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    caplog.set_level(logging.WARNING, logger="hi_agent.server.run_store")
    rec = RunRecord(**_full_run_record(tenant_id=""))
    assert rec.tenant_id == ""
    assert any("run_record_spine_incomplete" in r.message for r in caplog.records)


# --- StoredEvent -----------------------------------------------------------

def _full_stored_event(**overrides) -> dict:
    base = dict(
        event_id="ev-1",
        run_id="run-1",
        sequence=0,
        event_type="run_started",
        payload_json="{}",
        tenant_id="tenant-A",
    )
    base.update(overrides)
    return base


def test_stored_event_research_empty_run_id_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="run_id"):
        StoredEvent(**_full_stored_event(run_id=""))


def test_stored_event_research_empty_event_id_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="event_id"):
        StoredEvent(**_full_stored_event(event_id=""))


def test_stored_event_research_empty_tenant_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        StoredEvent(**_full_stored_event(tenant_id=""))


def test_stored_event_research_full_spine_succeeds(_research_posture: None) -> None:
    ev = StoredEvent(**_full_stored_event())
    assert ev.run_id == "run-1"
    assert ev.tenant_id == "tenant-A"


def test_stored_event_dev_warns_not_raises(
    _dev_posture: None, caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    caplog.set_level(logging.WARNING, logger="hi_agent.server.event_store")
    ev = StoredEvent(**_full_stored_event(tenant_id=""))
    assert ev.tenant_id == ""
    assert any("stored_event_spine_incomplete" in r.message for r in caplog.records)


# --- ManagedRun ------------------------------------------------------------

def test_managed_run_research_empty_run_id_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="run_id"):
        ManagedRun(run_id="", task_contract={}, tenant_id="tenant-A")


def test_managed_run_research_empty_tenant_raises(_research_posture: None) -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        ManagedRun(run_id="run-1", task_contract={}, tenant_id="")


def test_managed_run_research_full_spine_succeeds(_research_posture: None) -> None:
    run = ManagedRun(run_id="run-1", task_contract={}, tenant_id="tenant-A")
    assert run.run_id == "run-1"
    assert run.tenant_id == "tenant-A"


def test_managed_run_dev_warns_not_raises(
    _dev_posture: None, caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    caplog.set_level(logging.WARNING, logger="hi_agent.server.run_manager")
    run = ManagedRun(run_id="run-1", task_contract={}, tenant_id="")
    assert run.tenant_id == ""
    assert any("managed_run_spine_incomplete" in r.message for r in caplog.records)
