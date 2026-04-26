"""Integration tests: structured error envelope at /runs boundary.

CO-9: verifies that non-2xx responses from POST /runs include the full
error_response() envelope with all required fields.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hi_agent.server.app import AgentServer, build_app
from starlette.testclient import TestClient


def _make_minimal_client(monkeypatch=None, data_dir: str | None = None) -> TestClient:
    """Minimal server with no executor_factory — enough to test HTTP contract."""
    # Research/prod posture requires HI_AGENT_DATA_DIR for durable backends.
    if data_dir is not None and monkeypatch is not None:
        monkeypatch.setenv("HI_AGENT_DATA_DIR", data_dir)
    server = AgentServer()
    app = build_app(server)
    return TestClient(app, raise_server_exceptions=False)


def _post_run(client: TestClient, body: dict) -> Any:
    return client.post(
        "/runs",
        content=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )


@pytest.mark.integration
def test_scope_required_envelope_has_all_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """POST /runs without project_id under research posture → 400 with full envelope."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_minimal_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test"})
    assert resp.status_code == 400
    body = resp.json()

    for field in ("error_category", "message", "retryable", "next_action"):
        assert field in body, f"Missing field {field!r} in error envelope; body={body}"

    assert body["error_category"] == "scope_required"
    assert isinstance(body["message"], str) and len(body["message"]) > 0
    assert body["retryable"] is False
    assert isinstance(body["next_action"], str)


@pytest.mark.integration
def test_scope_required_profile_id_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """POST /runs without profile_id under research posture → 400 with full envelope."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_minimal_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test", "project_id": "proj-abc"})
    assert resp.status_code == 400
    body = resp.json()

    assert body["error_category"] == "scope_required"
    assert "profile_id" in body["message"]
    assert "retryable" in body
    assert "next_action" in body


@pytest.mark.integration
def test_error_category_values_are_strings(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """error_category field must be a string value (not an enum object)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_minimal_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test"})
    body = resp.json()
    # Must be JSON-serializable plain string, not an enum repr
    assert isinstance(body["error_category"], str)
    assert body["error_category"] == "scope_required"
