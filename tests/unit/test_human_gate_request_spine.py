"""Unit tests: HumanGateRequest / HumanGateResolution spine fields (W2-C.2).

Verifies that the agent-kernel ``HumanGateRequest`` and ``HumanGateResolution``
contracts carry the spine (tenant_id, user_id, session_id, project_id),
default to empty strings for back-compat with already-stored requests, and
round-trip through the HTTP serializer at
``agent_kernel/service/serialization.py:170``.
"""

from __future__ import annotations

from agent_kernel.kernel.contracts import HumanGateRequest, HumanGateResolution
from agent_kernel.service.serialization import deserialize_human_gate


def test_human_gate_request_has_spine_with_defaults() -> None:
    """Spine fields default to empty strings so already-stored gates
    deserialize without breakage."""
    req = HumanGateRequest(
        gate_ref="g1",
        gate_type="final_approval",
        run_id="r1",
        trigger_reason="approval needed",
        trigger_source="system",
    )
    assert req.tenant_id == ""
    assert req.user_id == ""
    assert req.session_id == ""
    assert req.project_id == ""


def test_human_gate_request_spine_settable() -> None:
    """All four spine fields must be settable at construction."""
    req = HumanGateRequest(
        gate_ref="g1",
        gate_type="final_approval",
        run_id="r1",
        trigger_reason="reason",
        trigger_source="system",
        tenant_id="tenant-a",
        user_id="user-b",
        session_id="sess-c",
        project_id="proj-d",
    )
    assert req.tenant_id == "tenant-a"
    assert req.user_id == "user-b"
    assert req.session_id == "sess-c"
    assert req.project_id == "proj-d"


def test_human_gate_resolution_has_spine_with_defaults() -> None:
    """HumanGateResolution must expose the same spine with empty defaults."""
    res = HumanGateResolution(
        gate_ref="g1",
        gate_type="final_approval",
        resolution="approved",
    )
    assert res.tenant_id == ""
    assert res.user_id == ""
    assert res.session_id == ""
    assert res.project_id == ""


def test_human_gate_resolution_spine_settable() -> None:
    """HumanGateResolution must accept spine values at construction."""
    res = HumanGateResolution(
        gate_ref="g1",
        gate_type="final_approval",
        resolution="approved",
        tenant_id="tenant-a",
        user_id="user-b",
        session_id="sess-c",
        project_id="proj-d",
    )
    assert res.tenant_id == "tenant-a"
    assert res.user_id == "user-b"
    assert res.session_id == "sess-c"
    assert res.project_id == "proj-d"


def test_deserialize_human_gate_propagates_spine() -> None:
    """The HTTP deserializer at agent_kernel/service/serialization.py:170
    must read the spine from the JSON body when present."""
    body = {
        "gate_ref": "g1",
        "gate_type": "final_approval",
        "trigger_reason": "needs review",
        "trigger_source": "system",
        "tenant_id": "tenant-http",
        "user_id": "user-http",
        "session_id": "sess-http",
        "project_id": "proj-http",
    }
    req = deserialize_human_gate("run-http-1", body)

    assert req.run_id == "run-http-1"
    assert req.gate_ref == "g1"
    assert req.tenant_id == "tenant-http"
    assert req.user_id == "user-http"
    assert req.session_id == "sess-http"
    assert req.project_id == "proj-http"


def test_deserialize_human_gate_back_compat_no_spine_keys() -> None:
    """A JSON body without spine keys deserializes with empty-string spine —
    legacy clients keep working."""
    body = {
        "gate_ref": "g1",
        "gate_type": "final_approval",
        "trigger_reason": "needs review",
        "trigger_source": "system",
    }
    req = deserialize_human_gate("run-legacy", body)

    assert req.run_id == "run-legacy"
    assert req.tenant_id == ""
    assert req.user_id == ""
    assert req.session_id == ""
    assert req.project_id == ""
