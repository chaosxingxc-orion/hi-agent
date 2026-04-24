"""Integration test: project_id threading through POST /runs HTTP contract.

Verifies:
- POST /runs without project_id returns X-Project-Warning: unscoped header.
- POST /runs with project_id does NOT return that header.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from starlette.testclient import TestClient

from hi_agent.contracts import TaskContract
from hi_agent.runner import RunExecutor
from hi_agent.server.app import AgentServer, build_app
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
        executor = RunExecutor(contract, kernel)
        return executor.execute

    return factory


@pytest.fixture()
def client() -> TestClient:
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


def test_missing_project_id_returns_warning_header(client: TestClient) -> None:
    """POST /runs without project_id must set X-Project-Warning: unscoped."""
    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code in (201, 503), f"Unexpected status: {resp.status_code}"
    assert resp.headers.get("X-Project-Warning") == "unscoped", (
        f"Expected X-Project-Warning: unscoped, got headers: {dict(resp.headers)}"
    )


def test_with_project_id_no_warning_header(client: TestClient) -> None:
    """POST /runs with project_id must NOT set X-Project-Warning."""
    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    assert resp.status_code in (201, 503), f"Unexpected status: {resp.status_code}"
    assert "X-Project-Warning" not in resp.headers, (
        f"X-Project-Warning should be absent when project_id provided, "
        f"got headers: {dict(resp.headers)}"
    )
