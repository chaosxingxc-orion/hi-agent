"""Tests that agent_server package tree is importable."""
import importlib
import os

import pytest


def test_agent_server_importable():
    mod = importlib.import_module("agent_server")
    assert mod.AGENT_SERVER_API_VERSION == "v1"


def test_required_subpackages_exist():
    subpackages = [
        "contracts", "api", "mcp", "facade",
        "tenancy", "workspace", "cli", "config", "observability",
    ]
    for sub in subpackages:
        importlib.import_module(f"agent_server.{sub}")


def test_config_submodules_exist():
    importlib.import_module("agent_server.config.version")
    importlib.import_module("agent_server.config.settings")


def test_api_version_constant():
    from agent_server.config.version import API_VERSION, SCHEMA_VERSION
    assert API_VERSION == "v1"
    assert SCHEMA_VERSION == "1.0"


def test_load_settings_invalid_port_raises():
    from agent_server.config.settings import load_settings
    env_bak = os.environ.copy()
    try:
        os.environ["AGENT_SERVER_PORT"] = "not_a_number"
        with pytest.raises(ValueError, match="AGENT_SERVER_PORT must be an integer"):
            load_settings()
    finally:
        os.environ.clear()
        os.environ.update(env_bak)
