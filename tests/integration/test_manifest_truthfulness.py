"""Manifest truthfulness tests — HI-W1-D4-001.

Verify that /manifest reports runtime_mode, llm_mode, and evolve_policy
using the same resolvers as /ready, so the two endpoints never drift.
"""

from __future__ import annotations

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient backed by a real AgentServer in dev mode.

    Suppresses JSON config gateway so tests stay in heuristic/dev-smoke mode
    even if a local llm_config.json with credentials is present.
    """
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manifest_runtime_mode_reflects_env_dev(test_client: TestClient) -> None:
    """In dev env, runtime_mode must be dev-smoke (no real LLM/kernel)."""
    resp = test_client.get("/manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["runtime_mode"] in ("dev-smoke", "local-real", "prod-real")
    # In the test environment (HI_AGENT_ENV=dev, no real LLM creds), must be dev-smoke.
    assert data["runtime_mode"] == "dev-smoke"


def test_manifest_and_ready_runtime_mode_aligned(test_client: TestClient) -> None:
    """runtime_mode in /manifest must equal runtime_mode in /ready."""
    manifest = test_client.get("/manifest").json()
    ready = test_client.get("/ready").json()
    # Both should report the same runtime_mode — they must use the same resolver.
    assert manifest.get("runtime_mode") == ready.get("runtime_mode")


def test_manifest_evolve_policy_present(test_client: TestClient) -> None:
    """evolve_policy dict must be present with mode, effective, source."""
    data = test_client.get("/manifest").json()
    assert "evolve_policy" in data
    ep = data["evolve_policy"]
    assert "mode" in ep
    assert "effective" in ep
    assert "source" in ep
    assert ep["mode"] in ("auto", "on", "off")
    assert isinstance(ep["effective"], bool)


def test_manifest_provenance_contract_version_present(test_client: TestClient) -> None:
    """provenance_contract_version must match the locked CONTRACT_VERSION."""
    from hi_agent.contracts.execution_provenance import CONTRACT_VERSION

    data = test_client.get("/manifest").json()
    assert data.get("provenance_contract_version") == CONTRACT_VERSION


def test_manifest_passes_through_llm_observability(monkeypatch: pytest.MonkeyPatch) -> None:
    """/manifest must surface readiness LLM observability without secrets."""

    class _FakeModel:
        def __init__(self, name: str, provider: str, tier: str = "medium") -> None:
            self.model_id = name
            self.provider = provider
            self.tier = tier

    class _FakeRegistry:
        def list_all(self) -> list[_FakeModel]:
            return [_FakeModel("claude-sonnet-4-6", "anthropic")]

        def list_models(self) -> list[_FakeModel]:
            return self.list_all()

    class _FakeBackend:
        pass

    class _FakeGateway:
        def __init__(self) -> None:
            self._inner = _FakeBackend()
            self._registry = _FakeRegistry()

    class _FakeInvoker:
        def __init__(self) -> None:
            self.registry = type("_Reg", (), {"list_names": lambda self: []})()

    class _FakeSkillLoader:
        def discover(self) -> int:
            return 0

        def list_skills(self) -> list[object]:
            return []

    class _FakeBuilder:
        def __init__(self) -> None:
            self._config = type(
                "_Cfg",
                (),
                {"evolve_mode": "auto", "llm_default_provider": "anthropic"},
            )()
            self._plugin_loader = type("_PL", (), {"list_loaded": lambda self: []})()

        def readiness(self) -> dict[str, object]:
            return {
                "ready": True,
                "health": "ok",
                "execution_mode": "local",
                "kernel_mode": "local-fsm",
                "llm_mode": "real",
                "llm_provider": "anthropic",
                "llm_backend": "_FakeBackend",
                "models": [
                    {
                        "name": "claude-sonnet-4-6",
                        "provider": "anthropic",
                        "tier": "medium",
                        "status": "configured",
                    }
                ],
            }

        def build_invoker(self) -> _FakeInvoker:
            return _FakeInvoker()

        def build_skill_loader(self) -> _FakeSkillLoader:
            return _FakeSkillLoader()

    server = AgentServer(rate_limit_rps=10000)
    server._builder = _FakeBuilder()
    with TestClient(server.app, raise_server_exceptions=False) as client:
        data = client.get("/manifest").json()

    assert data["llm_mode"] == "real"
    assert data["llm_provider"] == "anthropic"
    assert data["llm_backend"] == "_FakeBackend"
    assert data["models"] == [
        {
            "name": "claude-sonnet-4-6",
            "provider": "anthropic",
            "tier": "medium",
            "status": "configured",
        }
    ]
    llm_summary = {
        "llm_mode": data["llm_mode"],
        "llm_provider": data["llm_provider"],
        "llm_backend": data["llm_backend"],
        "models": data["models"],
    }
    assert "sk-" not in str(llm_summary)
