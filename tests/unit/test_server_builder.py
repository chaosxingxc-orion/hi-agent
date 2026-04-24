"""Unit tests for ServerBuilder extraction from SystemBuilder."""

import inspect

import pytest
from hi_agent.config.trace_config import TraceConfig
from hi_agent.server.app import AgentServer
from hi_agent.server.run_manager import RunManager


class FakeAgentServer:
    def __init__(self, host="0.0.0.0", port=8080, **kwargs):
        self.host = host
        self.port = port
        self.kwargs = kwargs
        self.server_address = (host, port)


@pytest.fixture()
def fake_agent_server(monkeypatch):
    from hi_agent.config import server_builder

    monkeypatch.setattr(server_builder, "AgentServer", FakeAgentServer)
    return FakeAgentServer


def test_build_server_returns_agent_server():
    from hi_agent.config.server_builder import ServerBuilder

    config = TraceConfig(server_host="127.0.0.1", server_port=7878)
    server = ServerBuilder(config).build_server()

    assert isinstance(server, AgentServer)
    assert server.server_address == ("127.0.0.1", 7878)


def test_run_manager_wired(fake_agent_server):
    from hi_agent.config.server_builder import ServerBuilder

    config = TraceConfig(server_max_concurrent_runs=7)
    server = ServerBuilder(config).build_server()

    assert isinstance(server.run_manager, RunManager)
    assert server.run_manager._max_concurrent == 7


def test_injected_memory_manager_set(fake_agent_server):
    from hi_agent.config.server_builder import ServerBuilder

    memory_manager = object()
    server = ServerBuilder(TraceConfig()).build_server(memory_manager=memory_manager)

    assert server.memory_manager is memory_manager


def test_injected_metrics_wired_to_slo(fake_agent_server):
    from hi_agent.config.server_builder import ServerBuilder

    metrics_collector = object()
    server = ServerBuilder(TraceConfig()).build_server(metrics_collector=metrics_collector)

    assert server.metrics_collector is metrics_collector
    assert server.slo_monitor._metrics is metrics_collector


def test_system_builder_build_server_works(monkeypatch, fake_agent_server):
    from hi_agent.config.builder import SystemBuilder

    builder = SystemBuilder(TraceConfig(server_host="127.0.0.1", server_port=9090))
    skill_evolver = object()
    skill_loader = object()
    metrics_collector = object()
    run_context_manager = object()

    # Rule 13 (DF-12): memory_manager / knowledge_manager are per-profile and
    # are no longer pre-built at server construction time.
    monkeypatch.setattr(builder, "build_skill_evolver", lambda: skill_evolver)
    monkeypatch.setattr(builder, "build_skill_loader", lambda: skill_loader)
    monkeypatch.setattr(builder, "build_metrics_collector", lambda: metrics_collector)
    monkeypatch.setattr(builder, "_build_run_context_manager", lambda: run_context_manager)

    server = builder.build_server()

    assert isinstance(server, FakeAgentServer)
    assert server.server_address == ("127.0.0.1", 9090)
    assert server.skill_evolver is skill_evolver
    assert server.skill_loader is skill_loader
    assert server.metrics_collector is metrics_collector
    assert server.run_context_manager is run_context_manager


def test_standalone(fake_agent_server):
    from hi_agent.config.server_builder import ServerBuilder

    sig = inspect.signature(ServerBuilder.__init__)
    params = list(sig.parameters.keys())

    assert "builder" not in params
    assert "config" in params
    assert "SystemBuilder" not in inspect.getsource(ServerBuilder)

    server = ServerBuilder(TraceConfig(server_port=8181)).build_server()

    assert isinstance(server, FakeAgentServer)
    assert server.server_address == ("0.0.0.0", 8181)
    assert isinstance(server.run_manager, RunManager)
