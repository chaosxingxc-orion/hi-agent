"""W34-F.3 / B-W34-2: ReasoningTrace.__post_init__ spine validation.

Closes the W33 carryover F.3: ``ReasoningTrace`` had no ``__post_init__``,
so a buggy constructor anywhere in the kernel could silently emit traces
with empty spine fields.

Layer: unit (Rule 4 Layer 1).
"""
from __future__ import annotations

import os

import pytest

from hi_agent.contracts.reasoning import ReasoningTrace, SpineCompletenessError


@pytest.fixture
def _research_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin posture to research so fail-closed validation fires."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")


@pytest.fixture
def _dev_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin posture to dev so the check degrades to a logged warning."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


# --- Strict (research/prod) posture ----------------------------------------

def test_research_empty_tenant_raises(_research_posture: None) -> None:
    """Empty tenant_id under research posture must raise."""
    with pytest.raises(SpineCompletenessError) as exc_info:
        ReasoningTrace(run_id="run-1", stage_id="S2", tenant_id="")
    assert "tenant_id" in str(exc_info.value)


def test_research_empty_run_id_raises(_research_posture: None) -> None:
    """Empty run_id under research posture must raise."""
    with pytest.raises(SpineCompletenessError) as exc_info:
        ReasoningTrace(run_id="", stage_id="S2", tenant_id="tenant-A")
    assert "run_id" in str(exc_info.value)


def test_research_empty_stage_id_raises(_research_posture: None) -> None:
    """Empty stage_id under research posture must raise."""
    with pytest.raises(SpineCompletenessError) as exc_info:
        ReasoningTrace(run_id="run-1", stage_id="", tenant_id="tenant-A")
    assert "stage_id" in str(exc_info.value)


def test_research_multiple_missing_fields_listed(_research_posture: None) -> None:
    """All missing spine fields surface in the exception message."""
    with pytest.raises(SpineCompletenessError) as exc_info:
        ReasoningTrace(run_id="", stage_id="", tenant_id="")
    msg = str(exc_info.value)
    assert "run_id" in msg
    assert "stage_id" in msg
    assert "tenant_id" in msg


def test_research_complete_spine_succeeds(_research_posture: None) -> None:
    """All spine fields present under research → constructor succeeds."""
    trace = ReasoningTrace(run_id="run-1", stage_id="S2", tenant_id="tenant-A")
    assert trace.run_id == "run-1"
    assert trace.tenant_id == "tenant-A"
    assert trace.stage_id == "S2"


def test_typed_subclass_of_value_error(_research_posture: None) -> None:
    """SpineCompletenessError must be catchable via ValueError for back-compat."""
    with pytest.raises(ValueError):
        ReasoningTrace(run_id="run-1", stage_id="S2", tenant_id="")


# --- Permissive (dev) posture ----------------------------------------------

def test_dev_empty_tenant_warns_not_raises(
    _dev_posture: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Under dev posture, an empty tenant emits a warning instead of raising."""
    import logging
    caplog.set_level(logging.WARNING, logger="hi_agent.contracts.reasoning")
    trace = ReasoningTrace(run_id="run-1", stage_id="S2", tenant_id="")
    # Constructor returned successfully under dev.
    assert trace.tenant_id == ""
    # And we logged the gap so a developer running under dev can see it.
    assert any(
        "reasoning_trace_spine_incomplete" in rec.message
        for rec in caplog.records
    )


def test_dev_complete_spine_no_warning(
    _dev_posture: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Complete spine under dev posture emits no warning."""
    import logging
    caplog.set_level(logging.WARNING, logger="hi_agent.contracts.reasoning")
    ReasoningTrace(run_id="run-1", stage_id="S2", tenant_id="tenant-A")
    relevant = [r for r in caplog.records if "spine_incomplete" in r.message]
    assert relevant == []


# --- Round-trip via from_dict ----------------------------------------------

def test_from_dict_under_research_validates_spine(_research_posture: None) -> None:
    """``from_dict`` deserialisation runs the same validation."""
    with pytest.raises(SpineCompletenessError):
        ReasoningTrace.from_dict({"run_id": "run-1", "stage_id": "S2", "tenant_id": ""})


def test_from_dict_under_research_succeeds_with_full_spine(
    _research_posture: None,
) -> None:
    """Deserialisation of a complete record succeeds."""
    trace = ReasoningTrace.from_dict({
        "run_id": "run-1",
        "stage_id": "S2",
        "tenant_id": "tenant-A",
        "trace_id": "tr-1",
        "steps": [],
    })
    assert trace.run_id == "run-1"
    assert trace.tenant_id == "tenant-A"
