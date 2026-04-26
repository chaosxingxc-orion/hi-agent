"""Integration tests: posture-driven project_id and profile_id enforcement.

CO-2: dev posture allows missing project_id (warning header); research/prod blocks (400).
CO-3: dev posture allows missing profile_id (fallback to 'default'); research/prod blocks (400).
CO-9: 400 responses use structured error_response() envelope.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from hi_agent.contracts import CTSExplorationBudget, TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.l0_raw import RawMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.runner import RunExecutor
from hi_agent.server.app import AgentServer, build_app
from starlette.testclient import TestClient

from tests.helpers.kernel_adapter_fixture import MockKernel


def _make_factory():
    def factory(run_data: dict[str, Any]):
        task_id = run_data.get("task_id") or run_data.get("run_id") or uuid.uuid4().hex[:12]
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            project_id=run_data.get("project_id", ""),
        )
        kernel = MockKernel()
        executor = RunExecutor(
            contract,
            kernel,
            raw_memory=RawMemoryStore(),
            event_emitter=EventEmitter(),
            compressor=MemoryCompressor(),
            acceptance_policy=AcceptancePolicy(),
            cts_budget=CTSExplorationBudget(),
            policy_versions=PolicyVersionSet(),
        )
        return executor.execute

    return factory


def _make_client(monkeypatch=None, data_dir: str | None = None) -> TestClient:
    # Research/prod posture requires HI_AGENT_DATA_DIR for durable backends.
    # When data_dir is provided, set it before constructing AgentServer.
    if data_dir is not None and monkeypatch is not None:
        monkeypatch.setenv("HI_AGENT_DATA_DIR", data_dir)
    server = AgentServer()
    server.executor_factory = _make_factory()
    app = build_app(server)
    return TestClient(app, raise_server_exceptions=False)


def _post_run(client: TestClient, body: dict) -> Any:
    return client.post(
        "/runs",
        content=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# CO-2: project_id posture tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dev_posture_allows_missing_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev posture: missing project_id is allowed; warning header emitted."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code in (201, 503), (
        f"Dev posture should allow missing project_id; got {resp.status_code}"
    )
    assert resp.headers.get("X-Hi-Agent-Warning") == "project_id-missing", (
        f"Expected X-Hi-Agent-Warning: project_id-missing, got: {dict(resp.headers)}"
    )


@pytest.mark.integration
def test_research_posture_blocks_missing_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Research posture: missing project_id → 400 with scope_required error_category."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code == 400, (
        f"Research posture must block missing project_id; got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error_category") == "scope_required", f"Unexpected body: {body}"
    assert body.get("field") is None or "project_id" in body.get("message", ""), (
        f"Error message should reference project_id; body: {body}"
    )
    assert "retryable" in body, f"error_response envelope missing 'retryable': {body}"
    assert "next_action" in body, f"error_response envelope missing 'next_action': {body}"


@pytest.mark.integration
def test_prod_posture_blocks_missing_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Prod posture: missing project_id → 400."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code == 400, (
        f"Prod posture must block missing project_id; got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error_category") == "scope_required", f"Unexpected body: {body}"


@pytest.mark.integration
def test_research_posture_passes_when_project_id_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Research posture: project_id present → not blocked."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(
        client, {"goal": "test goal", "project_id": "proj-abc", "profile_id": "default"}
    )
    assert resp.status_code != 400, (
        f"Should not be 400 when project_id and profile_id provided; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# CO-3: profile_id posture tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dev_posture_allows_missing_profile_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dev posture: missing profile_id is allowed; fallback to 'default'."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    assert resp.status_code in (201, 503), (
        f"Dev posture should allow missing profile_id; got {resp.status_code}"
    )


@pytest.mark.integration
def test_research_posture_blocks_missing_profile_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Research posture: missing profile_id → 400 with scope_required error_category."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    assert resp.status_code == 400, (
        f"Research posture must block missing profile_id; got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error_category") == "scope_required", f"Unexpected body: {body}"
    assert "profile_id" in body.get("message", ""), (
        f"Error message should reference profile_id; body: {body}"
    )


@pytest.mark.integration
def test_research_posture_passes_when_profile_id_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Research posture: both IDs present → not blocked."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(
        client,
        {"goal": "test goal", "project_id": "proj-abc", "profile_id": "default"},
    )
    assert resp.status_code != 400, (
        f"Should not be 400 when both IDs provided; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# CO-9: error envelope shape
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_error_envelope_has_required_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """400 from /runs must have all error_response() envelope fields."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code == 400
    body = resp.json()
    for field in ("error_category", "message", "retryable", "next_action"):
        assert field in body, f"error envelope missing field {field!r}; body: {body}"
    assert body["retryable"] is False
    assert body["error_category"] == "scope_required"
