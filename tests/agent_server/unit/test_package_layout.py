"""Tests that agent_server package tree is importable."""
import importlib
import os

import pytest


def test_agent_server_importable():
    mod = importlib.import_module("agent_server")
    assert mod.AGENT_SERVER_API_VERSION == "v1"


def test_required_subpackages_exist():
    # W31-H7: empty shell subpackages mcp/, observability/, tenancy/,
    # workspace/ removed; their responsibilities live in hi_agent/ and the
    # contract layer. See agent_server/ARCHITECTURE.md §2 and
    # docs/governance/package-consolidation-2026-05-02.md.
    subpackages = ["contracts", "api", "facade", "cli", "config"]
    for sub in subpackages:
        importlib.import_module(f"agent_server.{sub}")


def test_removed_shell_subpackages_no_longer_importable():
    """W31-H7: the four bare shells must not re-appear under agent_server/."""
    removed = ["mcp", "observability", "tenancy", "workspace"]
    for sub in removed:
        with pytest.raises(ModuleNotFoundError):
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
