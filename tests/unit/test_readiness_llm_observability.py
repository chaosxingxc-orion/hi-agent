"""Readiness LLM observability tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from hi_agent.config.readiness import ReadinessProbe


@pytest.fixture(autouse=True)
def _force_dev_posture(monkeypatch) -> None:
    """W33 Track E.1: pin posture to dev so the readiness snapshot does not
    emit the prod prerequisites block (which mentions OPENAI_API_KEY etc.).
    Both HI_AGENT_POSTURE and HI_AGENT_ENV unset now defaults to 'prod'.
    """
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")


class _FakeModel:
    def __init__(self, name: str, provider: str, tier: str = "medium") -> None:
        self.model_id = name
        self.provider = provider
        self.tier = tier


class _FakeRegistry:
    def __init__(self, models: list[_FakeModel]) -> None:
        self._models = models

    def list_all(self) -> list[_FakeModel]:
        return list(self._models)

    def list_models(self) -> list[_FakeModel]:
        return list(self._models)


class _FakeBackend:
    pass


class _FakeGateway:
    def __init__(self, backend: object, registry: _FakeRegistry) -> None:
        self._inner = backend
        self._registry = registry


class _FakeInvokerRegistry:
    def list_names(self) -> list[str]:
        return ["capability-a"]


class _FakeInvoker:
    def __init__(self) -> None:
        self.registry = _FakeInvokerRegistry()


class _FakeSkillLoader:
    def discover(self) -> int:
        return 1

    def list_skills(self) -> list[object]:
        return []


class _FakeMCPRegistry:
    def list_servers(self) -> list[dict[str, object]]:
        return []


class _FakePluginLoader:
    def list_loaded(self) -> list[dict[str, object]]:
        return []


class _FakeBuilder:
    def __init__(self, gateway: object | None, *, provider: str = "openai") -> None:
        self._config = SimpleNamespace(
            kernel_base_url="local",
            llm_default_provider=provider,
            llm_mode="",
            kernel_mode="",
        )
        self._gateway = gateway
        self._tier_router = None
        self._mcp_registry = _FakeMCPRegistry()
        self._plugin_loader = _FakePluginLoader()

    def build_kernel(self) -> object:
        return object()

    def build_llm_gateway(self) -> object | None:
        return self._gateway

    def build_invoker(self) -> _FakeInvoker:
        return _FakeInvoker()

    def build_skill_loader(self) -> _FakeSkillLoader:
        return _FakeSkillLoader()


def test_readiness_reports_real_provider_backend_and_models_without_secrets() -> None:
    builder = _FakeBuilder(
        _FakeGateway(_FakeBackend(), _FakeRegistry([_FakeModel("gpt-4o", "openai")])),
    )

    snap = ReadinessProbe(builder).snapshot()

    assert snap["llm_mode"] == "real"
    assert snap["llm_provider"] == "openai"
    assert snap["llm_backend"] == "_FakeBackend"
    assert snap["models"] == [
        {"name": "gpt-4o", "provider": "openai", "tier": "medium", "status": "configured"}
    ]
    rendered = json.dumps(snap, sort_keys=True)
    assert "sk-" not in rendered
    assert "api_key" not in rendered.lower()


def test_readiness_reports_heuristic_when_llm_gateway_is_missing() -> None:
    builder = _FakeBuilder(None)

    snap = ReadinessProbe(builder).snapshot()

    assert snap["llm_mode"] == "heuristic"
    assert snap["llm_provider"] == "not_configured"
    assert snap["llm_backend"] == "none"
    assert snap["models"] == []
