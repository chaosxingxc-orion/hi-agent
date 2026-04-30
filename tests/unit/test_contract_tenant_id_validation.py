"""Posture-aware tenant_id validation tests for Wave 23 Track D dataclasses.

For each of the nine dataclasses closed in Track D, instantiating with empty
``tenant_id`` MUST:

- raise ``ValueError`` under research/prod posture (Rule 11 + Rule 12);
- emit a deprecation warning under dev posture, but allow construction
  (back-compat for legacy callers).
"""

from __future__ import annotations

import logging

import pytest

# Each entry: (class_name, ctor_kwargs without tenant_id) — the ctor MUST be
# constructable with these kwargs alone (i.e. all required fields supplied).
_TARGETS: list[tuple[str, dict]] = [
    ("StartRunRequest", {"task_contract": {"goal": "t"}}),
    ("StartRunResponse", {"run_id": "r-1"}),
    ("SignalRunRequest", {"run_id": "r-1", "signal_type": "abort"}),
    ("QueryRunResponse", None),  # filled in below — needs RunState
    ("TraceRuntimeView", {"run_id": "r-1"}),
    ("OpenBranchRequest", {"run_id": "r-1", "stage_id": "s", "branch_id": "b"}),
    ("BranchStateUpdateRequest", None),  # filled below — needs BranchState
    ("ApprovalRequest", {"gate_ref": "g-1", "decision": "approved"}),
    ("KernelManifest", {}),
]


@pytest.fixture(autouse=True)
def _isolate_posture(monkeypatch):
    """Make sure each test fully owns the HI_AGENT_POSTURE env var."""
    monkeypatch.delenv("HI_AGENT_POSTURE", raising=False)
    yield


def _resolve_ctor_kwargs(name: str, kwargs: dict | None) -> dict:
    if kwargs is not None:
        return dict(kwargs)
    if name == "QueryRunResponse":
        from hi_agent.contracts.run import RunState

        return {"run_id": "r-1", "state": RunState.CREATED}
    if name == "BranchStateUpdateRequest":
        from hi_agent.contracts.branch import BranchState

        return {"run_id": "r-1", "branch_id": "b-1", "target_state": BranchState.ACTIVE}
    raise AssertionError(f"missing ctor kwargs for {name}")


@pytest.mark.parametrize("posture_name", ["research", "prod"])
@pytest.mark.parametrize("name,_raw_kwargs", _TARGETS)
def test_strict_posture_rejects_empty_tenant_id(
    monkeypatch, posture_name: str, name: str, _raw_kwargs: dict | None
) -> None:
    """Empty tenant_id under research/prod must raise ValueError."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts import requests as mod

    cls = getattr(mod, name)
    kwargs = _resolve_ctor_kwargs(name, _raw_kwargs)
    with pytest.raises(ValueError, match="tenant_id"):
        cls(**kwargs)


@pytest.mark.parametrize("name,_raw_kwargs", _TARGETS)
def test_dev_posture_warns_and_constructs(
    monkeypatch, caplog, name: str, _raw_kwargs: dict | None
) -> None:
    """Empty tenant_id under dev must construct successfully but emit a warning."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    from hi_agent.contracts import requests as mod

    cls = getattr(mod, name)
    kwargs = _resolve_ctor_kwargs(name, _raw_kwargs)
    with caplog.at_level(logging.WARNING, logger="hi_agent.contracts.requests"):
        instance = cls(**kwargs)  # MUST NOT raise
    assert instance is not None
    assert any(
        "tenant_id" in record.getMessage() for record in caplog.records
    ), f"expected dev-posture warning for {name}; got: {[r.getMessage() for r in caplog.records]}"


@pytest.mark.parametrize("posture_name", ["research", "prod", "dev"])
@pytest.mark.parametrize("name,_raw_kwargs", _TARGETS)
def test_explicit_tenant_id_constructs_without_warning_or_raise(
    monkeypatch, caplog, posture_name: str, name: str, _raw_kwargs: dict | None
) -> None:
    """A non-empty tenant_id satisfies the spine under all postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", posture_name)
    from hi_agent.contracts import requests as mod

    cls = getattr(mod, name)
    kwargs = _resolve_ctor_kwargs(name, _raw_kwargs)
    kwargs["tenant_id"] = "tenant-abc"
    with caplog.at_level(logging.WARNING, logger="hi_agent.contracts.requests"):
        instance = cls(**kwargs)
    assert instance.tenant_id == "tenant-abc"
    # No warning about tenant_id should be emitted for the happy path.
    tenant_warnings = [
        record
        for record in caplog.records
        if "tenant_id" in record.getMessage() and record.levelno >= logging.WARNING
    ]
    assert tenant_warnings == [], (
        f"unexpected tenant_id warnings under {posture_name} for {name}: "
        f"{[r.getMessage() for r in tenant_warnings]}"
    )
