"""Tests that agent_server package tree is importable."""
import importlib


def test_agent_server_importable():
    mod = importlib.import_module("agent_server")
    assert mod.AGENT_SERVER_API_VERSION == "v1"


def test_required_subpackages_exist():
    subpackages = [
        "contracts", "api", "mcp", "facade",
        "tenancy", "workspace", "cli", "config", "observability",
    ]
    for sub in subpackages:
        mod = importlib.import_module(f"agent_server.{sub}")
        assert mod is not None, f"agent_server.{sub} failed to import"


def test_config_submodules_exist():
    importlib.import_module("agent_server.config.version")
    importlib.import_module("agent_server.config.settings")


def test_api_version_constant():
    from agent_server.config.version import API_VERSION, SCHEMA_VERSION
    assert API_VERSION == "v1"
    assert SCHEMA_VERSION == "1.0"
