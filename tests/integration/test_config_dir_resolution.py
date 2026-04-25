"""Integration tests for H1 Track5 config-dir resolution and strict-mode gates.

Tests:
1. SystemBuilder(config_dir=...) loads tools.json from that directory.
2. HI_AGENT_PROJECT_ID_REQUIRED=1 + missing project_id -> 400.
3. HI_AGENT_PROFILE_ID_REQUIRED=1 + missing profile_id -> 400.
4. Existing non-strict behaviour is unaffected when env vars are not set.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.config.builder import SystemBuilder
from hi_agent.server.app import AgentServer, build_app
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_tools_json(directory: Path, tool_name: str = "custom_echo_tool") -> None:
    """Write a minimal tools.json with one custom HTTP tool to *directory*."""
    tools_cfg = {
        "version": "1.0",
        "tools": [
            {
                "name": tool_name,
                "description": "Test tool loaded from custom config_dir",
                "handler": {
                    "type": "http",
                    "url": "http://localhost:9999/echo",
                    "method": "POST",
                },
                "input_schema": {"type": "object", "properties": {"msg": {"type": "string"}}},
            }
        ],
    }
    (directory / "tools.json").write_text(json.dumps(tools_cfg), encoding="utf-8")


def _make_factory():
    """Minimal executor factory that satisfies the server without real LLM."""
    from hi_agent.contracts import TaskContract
    from hi_agent.memory.l0_raw import RawMemoryStore
    from hi_agent.runner import RunExecutor

    from tests.helpers.kernel_adapter_fixture import MockKernel

    def factory(run_data: dict[str, Any]):
        task_id = run_data.get("task_id") or run_data.get("run_id") or uuid.uuid4().hex[:12]
        contract = TaskContract(
            task_id=task_id,
            goal=run_data.get("goal", ""),
            profile_id=run_data.get("profile_id", "default"),
            project_id=run_data.get("project_id", ""),
        )
        kernel = MockKernel()
        executor = RunExecutor(contract, kernel, raw_memory=RawMemoryStore())
        return executor.execute

    return factory


def _make_client() -> TestClient:
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
# Test 1 — custom config_dir resolves tools.json
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_custom_config_dir_loads_tools(tmp_path: Path) -> None:
    """SystemBuilder(config_dir=tmp_path) loads tools.json from that directory.

    The real CapabilityRegistry is used (no mocks) — Rule 4 Layer 2.
    """
    tool_name = f"test_tool_{uuid.uuid4().hex[:6]}"
    _write_tools_json(tmp_path, tool_name)

    builder = SystemBuilder(config_dir=tmp_path)
    registry: CapabilityRegistry | None = builder.build_capability_registry()

    assert registry is not None, "build_capability_registry() returned None"
    registered_names = set(registry.list_names())
    assert tool_name in registered_names, (
        f"Expected custom tool {tool_name!r} in registry; "
        f"got: {sorted(registered_names)}"
    )


@pytest.mark.integration
def test_env_var_config_dir_loads_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HI_AGENT_CONFIG_DIR env var points to tmp_path; tools.json is loaded from there."""
    tool_name = f"env_tool_{uuid.uuid4().hex[:6]}"
    _write_tools_json(tmp_path, tool_name)

    monkeypatch.setenv("HI_AGENT_CONFIG_DIR", str(tmp_path))
    builder = SystemBuilder()
    registry: CapabilityRegistry | None = builder.build_capability_registry()

    assert registry is not None
    assert tool_name in set(registry.list_names()), (
        f"Expected {tool_name!r} in registry via HI_AGENT_CONFIG_DIR"
    )


# ---------------------------------------------------------------------------
# Test 2 — HI_AGENT_PROJECT_ID_REQUIRED=1 → 400 when project_id missing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_project_id_required_strict_mode_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """HI_AGENT_PROJECT_ID_REQUIRED=1 + no project_id in body -> 400 missing_project_id."""
    monkeypatch.setenv("HI_AGENT_PROJECT_ID_REQUIRED", "1")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code == 400, (
        f"Expected 400 in strict project_id mode, got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error") == "missing_project_id", f"Unexpected body: {body}"


@pytest.mark.integration
def test_project_id_required_strict_mode_passes_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HI_AGENT_PROJECT_ID_REQUIRED=1 + project_id provided -> not 400."""
    monkeypatch.setenv("HI_AGENT_PROJECT_ID_REQUIRED", "1")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    assert resp.status_code != 400, (
        f"Should not be 400 when project_id is provided; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 3 — HI_AGENT_PROFILE_ID_REQUIRED=1 → 400 when profile_id missing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_profile_id_required_strict_mode_returns_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """HI_AGENT_PROFILE_ID_REQUIRED=1 + no profile_id in body -> 400 missing_profile_id."""
    monkeypatch.setenv("HI_AGENT_PROFILE_ID_REQUIRED", "1")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    assert resp.status_code == 400, (
        f"Expected 400 in strict profile_id mode, got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error") == "missing_profile_id", f"Unexpected body: {body}"


@pytest.mark.integration
def test_profile_id_required_strict_mode_passes_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HI_AGENT_PROFILE_ID_REQUIRED=1 + profile_id provided -> not 400."""
    monkeypatch.setenv("HI_AGENT_PROFILE_ID_REQUIRED", "1")
    client = _make_client()

    resp = _post_run(
        client,
        {"goal": "test goal", "project_id": "proj-123", "profile_id": "default"},
    )
    assert resp.status_code != 400, (
        f"Should not be 400 when profile_id is provided; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Non-strict behaviour preserved when env vars are not set
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_non_strict_project_id_returns_warning_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without HI_AGENT_PROJECT_ID_REQUIRED, missing project_id still gives X-Project-Warning."""
    monkeypatch.delenv("HI_AGENT_PROJECT_ID_REQUIRED", raising=False)
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code in (201, 503), f"Unexpected status: {resp.status_code}"
    assert resp.headers.get("X-Project-Warning") == "unscoped", (
        f"Expected X-Project-Warning: unscoped header, got: {dict(resp.headers)}"
    )


@pytest.mark.integration
def test_non_strict_profile_id_uses_default_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without HI_AGENT_PROFILE_ID_REQUIRED, missing profile_id falls back to 'default'."""
    monkeypatch.delenv("HI_AGENT_PROFILE_ID_REQUIRED", raising=False)
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    # Must not return 400 — the fallback path should be followed.
    assert resp.status_code in (201, 503), (
        f"Expected 201/503 (fallback), got {resp.status_code}: {resp.text}"
    )
