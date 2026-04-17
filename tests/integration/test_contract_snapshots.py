"""Contract snapshot tests — fix the shape of /manifest, /ready, and RunResult.

Run with UPDATE_SNAPSHOTS=1 pytest tests/integration/test_contract_snapshots.py
to regenerate snapshot files after intentional shape changes.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import pytest
from starlette.testclient import TestClient

from hi_agent.server.app import AgentServer

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "snapshots")
EXCLUDED_VOLATILE = {
    "timestamp", "started_at", "completed_at", "run_id",
    "uptime_seconds", "version",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient backed by a real AgentServer in dev mode."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_volatile(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in EXCLUDED_VOLATILE}


def _load_snapshot(name: str) -> dict:
    path = os.path.join(SNAPSHOT_DIR, name)
    with open(path) as f:
        return json.load(f)


def _assert_snapshot(data: dict, name: str) -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    path = os.path.join(SNAPSHOT_DIR, name)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        return
    expected = _load_snapshot(name)
    assert set(data.keys()) == set(expected.keys()), (
        f"Snapshot key mismatch [{name}].\n"
        f"Missing: {sorted(set(expected) - set(data))}\n"
        f"Extra:   {sorted(set(data) - set(expected))}\n"
        f"Run UPDATE_SNAPSHOTS=1 to regenerate."
    )
    assert data == expected, (
        f"Snapshot value mismatch [{name}]. Run UPDATE_SNAPSHOTS=1 to regenerate.\n"
        f"Diff: expected={expected!r}\n  actual={data!r}"
    )


def _wait_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> dict[str, Any]:
    """Poll GET /runs/{run_id} until terminal state, then return the run dict."""
    terminal = {"completed", "failed", "aborted"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200, f"Unexpected {resp.status_code}"
        data = resp.json()
        if data.get("state") in terminal:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Run {run_id!r} did not reach terminal state within {timeout:.1f}s")


# ── /manifest ──────────────────────────────────────────────────────────────────

def test_manifest_dev_smoke_shape_stable(test_client: TestClient) -> None:
    """Snapshot the stable structural keys of /manifest in dev-smoke mode."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    body = _strip_volatile(resp.json())
    snapshot_data = {
        k: body[k]
        for k in ("runtime_mode", "environment", "provenance_contract_version", "evolve_policy")
        if k in body
    }
    _assert_snapshot(snapshot_data, "manifest_dev_smoke.json")


# ── /ready ─────────────────────────────────────────────────────────────────────

def test_ready_dev_smoke_shape_stable(test_client: TestClient) -> None:
    """Snapshot the stable structural keys of /ready in dev-smoke mode."""
    resp = test_client.get("/ready")
    assert resp.status_code == 200
    body = _strip_volatile(resp.json())
    snapshot_data = {k: body[k] for k in ("ready", "status", "runtime_mode") if k in body}
    _assert_snapshot(snapshot_data, "ready_dev_smoke.json")


# ── RunResult ──────────────────────────────────────────────────────────────────

def test_run_result_provenance_shape_stable(test_client: TestClient) -> None:
    """Snapshot the execution_provenance shape inside RunResult after a completed run."""
    resp = test_client.post("/runs", json={"goal": "snapshot test"})
    assert resp.status_code in (200, 201, 202), (
        f"POST /runs failed: {resp.status_code} {resp.text}"
    )
    run_id = resp.json().get("run_id")
    assert run_id, "run_id must be present"

    final = _wait_terminal(test_client, run_id)
    result = final.get("result") or {}
    prov = result.get("execution_provenance") or {}

    snapshot_data = {
        "execution_provenance_keys": sorted(prov.keys()),
        "contract_version": prov.get("contract_version"),
        "fallback_used": prov.get("fallback_used"),
    }
    _assert_snapshot(snapshot_data, "run_result_dev_fallback.json")
