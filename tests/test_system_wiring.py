"""Tests for system wiring: builder, server, LLM gateway, CLI."""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import patch

from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.llm.anthropic_gateway import AnthropicLLMGateway
from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.tier_router import TierAwareLLMGateway
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.state import RunStateStore

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_contract(**overrides: Any) -> TaskContract:
    defaults: dict[str, Any] = {"task_id": "test_t1", "goal": "test goal"}
    defaults.update(overrides)
    return TaskContract(**defaults)


# ------------------------------------------------------------------
# Gap 1: SystemBuilder.build_executor wires ALL subsystems
# ------------------------------------------------------------------


class TestBuildExecutorWiring:
    """Verify build_executor produces a RunExecutor with all subsystems."""

    def test_all_subsystems_wired(self, tmp_path: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
        )
        builder = SystemBuilder(config)
        contract = _make_contract()
        executor = builder.build_executor(contract)

        # Core params
        assert executor.contract is contract
        assert executor.kernel is not None
        assert executor.evolve_engine is not None
        assert executor.harness_executor is not None

        # Newly wired subsystems
        assert isinstance(executor.event_emitter, EventEmitter)
        assert isinstance(executor.raw_memory, RawMemoryStore)
        assert isinstance(executor.compressor, MemoryCompressor)
        assert isinstance(executor.failure_collector, FailureCollector)
        assert isinstance(executor.watchdog, ProgressWatchdog)
        assert isinstance(executor.episode_builder, EpisodeBuilder)
        assert isinstance(executor.episodic_store, EpisodicMemoryStore)
        assert isinstance(executor.skill_recorder, SkillUsageRecorder)
        assert isinstance(executor.state_store, RunStateStore)
        assert isinstance(executor.policy_versions, PolicyVersionSet)
        assert isinstance(executor.route_engine, HybridRouteEngine)
        assert isinstance(executor.acceptance_policy, AcceptancePolicy)

    def test_compressor_helper(self, tmp_path: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
        )
        builder = SystemBuilder(config)
        compressor = builder._build_compressor()
        assert isinstance(compressor, MemoryCompressor)

    def test_route_engine_helper(self, tmp_path: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
        )
        builder = SystemBuilder(config)
        engine = builder._build_route_engine()
        assert isinstance(engine, HybridRouteEngine)

    def test_skill_recorder_helper(self, tmp_path: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
        )
        builder = SystemBuilder(config)
        recorder = builder._build_skill_recorder()
        assert isinstance(recorder, SkillUsageRecorder)


# ------------------------------------------------------------------
# Gap 2: AgentServer has executor_factory by default
# ------------------------------------------------------------------


class TestAgentServerFactory:
    """Verify AgentServer wires executor_factory automatically."""

    def test_executor_factory_not_none(self) -> None:
        from hi_agent.server.app import AgentServer

        server = AgentServer(host="127.0.0.1", port=9999)
        assert server.executor_factory is not None
        assert callable(server.executor_factory)

    def test_default_executor_factory_returns_callable(self) -> None:
        from hi_agent.server.app import AgentServer

        server = AgentServer(host="127.0.0.1", port=9999)
        run_data = {"goal": "test", "task_family": "quick_task", "risk_level": "low"}
        factory_result = server._default_executor_factory(run_data)
        assert callable(factory_result)

    def test_factory_run_executes(self) -> None:
        from hi_agent.server.app import AgentServer

        server = AgentServer(host="127.0.0.1", port=9999)
        run_data = {"goal": "greet the world", "task_family": "quick_task"}
        task_runner = server._default_executor_factory(run_data)
        result = task_runner()
        # Should complete without error and return a result dict
        assert result is not None

    def test_server_accepts_config(self) -> None:
        from hi_agent.server.app import AgentServer

        config = TraceConfig(server_host="127.0.0.1", server_port=9999)
        server = AgentServer(host="127.0.0.1", port=9999, config=config)
        assert server._config is config


# ------------------------------------------------------------------
# Gap 3: LLM Gateway auto-activation
# ------------------------------------------------------------------


class TestLLMGatewayActivation:
    """Verify build_llm_gateway auto-detects API keys."""

    def test_returns_none_without_env_vars(self, tmp_path: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
        )
        builder = SystemBuilder(config)
        # Ensure no API keys leak from the real env; suppress config-file fallback
        # so this test exercises the "truly no credentials" path.
        with (
            patch.dict(os.environ, {"HI_AGENT_ENV": "dev"}, clear=True),
            patch(
                "hi_agent.config.json_config_loader.build_gateway_from_config", return_value=None
            ),
        ):
            # Reset cached gateway
            builder._llm_gateway = None
            gateway = builder.build_llm_gateway()
        assert gateway is None

    def test_returns_gateway_with_openai_key(self, tmp_path: Any, monkeypatch: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
            compat_sync_llm=True,
        )
        builder = SystemBuilder(config)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-123")
        # Suppress config-file path so test exercises the env-var fallback.
        with patch(
            "hi_agent.config.json_config_loader.build_gateway_from_config", return_value=None
        ):
            gateway = builder.build_llm_gateway()
        assert isinstance(gateway, TierAwareLLMGateway)
        assert isinstance(gateway._inner, HttpLLMGateway)
        assert gateway._inner._default_model == "gpt-4o"

    def test_returns_gateway_with_anthropic_key(self, tmp_path: Any, monkeypatch: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
        )
        builder = SystemBuilder(config)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        # Suppress config-file path so test exercises the env-var fallback.
        with patch(
            "hi_agent.config.json_config_loader.build_gateway_from_config", return_value=None
        ):
            gateway = builder.build_llm_gateway()
        assert isinstance(gateway, TierAwareLLMGateway)
        assert isinstance(gateway._inner, AnthropicLLMGateway)
        assert gateway._inner._default_model == "claude-sonnet-4-6"

    def test_caches_gateway_instance(self, tmp_path: Any, monkeypatch: Any) -> None:
        config = TraceConfig(
            skill_storage_dir=str(tmp_path / "skills"),
            episodic_storage_dir=str(tmp_path / "episodes"),
            compat_sync_llm=True,
        )
        builder = SystemBuilder(config)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        gw1 = builder.build_llm_gateway()
        gw2 = builder.build_llm_gateway()
        assert gw1 is gw2


# ------------------------------------------------------------------
# CLI tests
# ------------------------------------------------------------------


class TestCLIRun:
    """Verify CLI run command with --local flag."""

    def test_local_run_executes(self, capsys: Any) -> None:
        from hi_agent.cli import _cmd_run, build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--goal",
                "say hello",
                "--local",
            ]
        )
        # Suppress config-file gateway fallback: this CLI test must run in
        # heuristic mode without real network calls.
        with patch(
            "hi_agent.config.json_config_loader.build_gateway_from_config", return_value=None
        ):
            _cmd_run(args)
        captured = capsys.readouterr()
        assert "Run completed" in captured.out


# ------------------------------------------------------------------
# Full round-trip: server -> POST /runs -> verify execution
# ------------------------------------------------------------------


class TestServerRoundTrip:
    """Full round-trip: create server, POST /runs, verify run executes."""

    def test_post_run_creates_and_starts(self) -> None:
        from hi_agent.server.app import AgentServer
        from starlette.testclient import TestClient

        server = AgentServer(host="127.0.0.1", port=9999)

        with TestClient(server.app) as client:
            # POST /runs
            resp = client.post("/runs", json={"goal": "test round trip"})
            data = resp.json()

            assert resp.status_code == 201
            assert "run_id" in data

            # Wait briefly for the background thread to finish
            run_id = data["run_id"]
            for _ in range(20):
                time.sleep(0.1)
                run = server.run_manager.get_run(run_id)
                if run and run.state in ("completed", "failed"):
                    break

            run = server.run_manager.get_run(run_id)
            assert run is not None
            assert run.state in ("completed", "failed", "running")
