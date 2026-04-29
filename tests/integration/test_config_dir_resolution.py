"""Integration tests for H1 Track5 config-dir resolution and posture-driven gates.

Tests:
1. SystemBuilder(config_dir=...) loads tools.json from that directory.
2. HI_AGENT_POSTURE=research + missing project_id -> 400.
3. HI_AGENT_POSTURE=research + missing profile_id -> 400.
4. Existing dev-posture behaviour is unaffected (permissive defaults).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hi_agent.capability.registry import CapabilityRegistry
from hi_agent.config.builder import SystemBuilder
from hi_agent.contracts import CTSExplorationBudget
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.memory import MemoryCompressor
from hi_agent.route_engine.acceptance import AcceptancePolicy
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
        f"Expected custom tool {tool_name!r} in registry; got: {sorted(registered_names)}"
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
# Test 2 — HI_AGENT_POSTURE=research → 400 when project_id missing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_project_id_required_strict_mode_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HI_AGENT_POSTURE=research + no project_id in body -> 400 scope_required."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code == 400, (
        f"Expected 400 in research posture, got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error_category") == "scope_required", f"Unexpected body: {body}"


@pytest.mark.integration
def test_project_id_required_strict_mode_passes_when_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HI_AGENT_POSTURE=research + project_id and profile_id provided -> not 400."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(
        client, {"goal": "test goal", "project_id": "proj-123", "profile_id": "default"}
    )
    assert resp.status_code != 400, (
        f"Should not be 400 when project_id and profile_id are provided; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 3 — HI_AGENT_POSTURE=research → 400 when profile_id missing
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_profile_id_required_strict_mode_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HI_AGENT_POSTURE=research + no profile_id in body -> 400 scope_required."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    assert resp.status_code == 400, (
        f"Expected 400 in research posture for missing profile_id, got {resp.status_code}"
    )
    body = resp.json()
    assert body.get("error_category") == "scope_required", f"Unexpected body: {body}"


@pytest.mark.integration
def test_profile_id_required_strict_mode_passes_when_provided(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HI_AGENT_POSTURE=research + profile_id provided -> not 400."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    client = _make_client(monkeypatch=monkeypatch, data_dir=str(tmp_path))

    resp = _post_run(
        client,
        {"goal": "test goal", "project_id": "proj-123", "profile_id": "default"},
    )
    assert resp.status_code != 400, (
        f"Should not be 400 when profile_id is provided; got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Dev-posture behaviour: permissive defaults
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_non_strict_project_id_returns_warning_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under dev posture, missing project_id gives X-Hi-Agent-Warning: project_id-missing."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal"})
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
    assert resp.headers.get("X-Hi-Agent-Warning") == "project_id-missing", (
        f"Expected X-Hi-Agent-Warning: project_id-missing header, got: {dict(resp.headers)}"
    )


@pytest.mark.integration
def test_non_strict_profile_id_uses_default_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Under dev posture, missing profile_id falls back to 'default'."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    client = _make_client()

    resp = _post_run(client, {"goal": "test goal", "project_id": "proj-123"})
    # Must not return 400 — the fallback path should be followed.
    assert resp.status_code == 201, (
        f"Expected 201 (fallback), got {resp.status_code}: {resp.text}"
    )
