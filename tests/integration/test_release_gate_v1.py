"""Integration tests for GET /ops/release-gate v1."""
import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient


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


def test_release_gate_returns_200_or_503(test_client):
    resp = test_client.get("/ops/release-gate")
    assert resp.status_code in (200, 503)


def test_release_gate_response_has_required_keys(test_client):
    resp = test_client.get("/ops/release-gate")
    body = resp.json()
    required = {"pass", "gates", "pass_gates", "skipped_gates", "failed_gates", "last_checked_at"}
    assert required.issubset(set(body.keys()))


def test_release_gate_gates_have_correct_shape(test_client):
    resp = test_client.get("/ops/release-gate")
    for gate in resp.json()["gates"]:
        assert "name" in gate
        assert "status" in gate
        assert "evidence" in gate
        assert gate["status"] in ("pass", "fail", "skipped", "info")


def test_release_gate_has_all_seven_gates(test_client):
    resp = test_client.get("/ops/release-gate")
    gate_names = {g["name"] for g in resp.json()["gates"]}
    expected = {
        "readiness", "doctor", "config_validation",
        "current_runtime_mode", "known_prerequisites", "mcp_health", "prod_e2e_recent"
    }
    assert expected == gate_names


def test_prod_e2e_recent_always_skipped(test_client):
    resp = test_client.get("/ops/release-gate")
    prod_e2e = next(g for g in resp.json()["gates"] if g["name"] == "prod_e2e_recent")
    assert prod_e2e["status"] == "skipped"


def test_current_runtime_mode_always_info(test_client):
    resp = test_client.get("/ops/release-gate")
    rt_gate = next(g for g in resp.json()["gates"] if g["name"] == "current_runtime_mode")
    assert rt_gate["status"] == "info"


def test_pass_true_when_no_failures_in_dev(test_client):
    resp = test_client.get("/ops/release-gate")
    body = resp.json()
    # In dev test environment: no blocking → pass should be True
    assert body["pass"] is True
    assert resp.status_code == 200


def test_counts_consistent(test_client):
    resp = test_client.get("/ops/release-gate")
    body = resp.json()
    gates = body["gates"]
    assert body["pass_gates"] == sum(1 for g in gates if g["status"] == "pass")
    assert body["skipped_gates"] == sum(1 for g in gates if g["status"] == "skipped")
    assert body["failed_gates"] == sum(1 for g in gates if g["status"] == "fail")
