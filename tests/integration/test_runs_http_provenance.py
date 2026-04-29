"""Layer 3 E2E: execution_provenance in HTTP /runs response — HI-W1-D3-001.

Drives the full HTTP path via starlette TestClient — no running server required.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

from tests._helpers.run_states import TERMINAL_STATES

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _dev_server(monkeypatch: pytest.MonkeyPatch) -> AgentServer:
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    return AgentServer(rate_limit_rps=10000)


@pytest.fixture()
def http_client(_dev_server: AgentServer) -> TestClient:
    return TestClient(_dev_server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_terminal(
    client: TestClient,
    run_id: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.1,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data.get("state") in TERMINAL_STATES:
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Run {run_id!r} did not reach terminal state within {timeout:.1f}s")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunsHttpProvenance:
    """Verify execution_provenance is present in the HTTP /runs result payload."""

    def test_provenance_in_run_result(self, http_client: TestClient) -> None:
        """POST /runs → execution_provenance dict must appear in result."""
        from hi_agent.contracts.execution_provenance import CONTRACT_VERSION

        resp = http_client.post("/runs", json={"goal": "test provenance shape"})
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        data = _wait_terminal(http_client, run_id)

        result = data.get("result", {})
        prov = result.get("execution_provenance")
        assert prov is not None, f"execution_provenance missing from result: {result}"
        assert prov.get("contract_version") == CONTRACT_VERSION
        expected_keys = {
            "contract_version",
            "runtime_mode",
            "llm_mode",
            "kernel_mode",
            "capability_mode",
            "mcp_transport",
            "fallback_used",
            "fallback_reasons",
            "evidence",
        }
        assert set(prov.keys()) == expected_keys
