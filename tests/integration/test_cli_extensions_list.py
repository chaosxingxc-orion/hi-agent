"""Integration: 'hi-agent extensions list/inspect' CLI subcommands.

Layer 2 — Integration: exercises the real CLI parser + real ExtensionRegistry.
No mocks on the subsystem under test.
"""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest
from hi_agent.cli import build_parser
from hi_agent.cli_commands.extensions import handle_extensions
from hi_agent.contracts.extension_manifest import get_extension_registry
from hi_agent.plugins.manifest import PluginManifest


@pytest.fixture(autouse=True)
def _clean_registry():
    """Remove test extensions from the global registry before and after each test."""
    registry = get_extension_registry()
    test_prefixes = ("__cli_test_ext__", "__cli_test_ext2__")

    def _purge():
        stale = [k for k in list(registry._manifests) if k.startswith(test_prefixes)]
        for k in stale:
            registry._manifests.pop(k, None)

    _purge()
    yield
    _purge()


def _run_extensions(argv: list[str]) -> tuple[int, str]:
    """Parse argv and invoke handle_extensions, capturing stdout.

    Returns (exit_code, captured_stdout).  exit_code 0 means success.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    captured = StringIO()
    exit_code = 0
    with patch("sys.stdout", captured):
        try:
            handle_extensions(args)
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    return exit_code, captured.getvalue()


def test_extensions_list_exits_zero_empty_registry() -> None:
    """'extensions list' exits 0 when the registry is empty."""
    code, _output = _run_extensions(["extensions", "list"])
    assert code == 0


def test_extensions_list_text_shows_registered() -> None:
    """'extensions list' text output shows the registered extension."""
    registry = get_extension_registry()
    registry.register(PluginManifest(name="__cli_test_ext__", version="3.0"))
    try:
        code, output = _run_extensions(["extensions", "list"])
        assert code == 0
        assert "__cli_test_ext__" in output
    finally:
        registry._manifests.pop("__cli_test_ext__", None)


def test_extensions_list_json_format() -> None:
    """'extensions list --format json' outputs valid JSON array."""
    registry = get_extension_registry()
    registry.register(PluginManifest(name="__cli_test_ext__", version="1.0"))
    try:
        code, output = _run_extensions(["extensions", "list", "--format", "json"])
        assert code == 0
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        names = [item["name"] for item in parsed]
        assert "__cli_test_ext__" in names
    finally:
        registry._manifests.pop("__cli_test_ext__", None)


def test_extensions_list_posture_filter() -> None:
    """'extensions list --posture research' excludes dev-only extensions."""
    registry = get_extension_registry()
    dev_only = PluginManifest(
        name="__cli_test_ext__",
        version="1.0",
        posture_support={"dev": True, "research": False, "prod": False},
    )
    all_postures = PluginManifest(
        name="__cli_test_ext2__",
        version="1.0",
        posture_support={"dev": True, "research": True, "prod": True},
    )
    registry.register(dev_only)
    registry.register(all_postures)
    try:
        code, output = _run_extensions(["extensions", "list", "--posture", "research"])
        assert code == 0
        assert "__cli_test_ext__" not in output
        assert "__cli_test_ext2__" in output
    finally:
        registry._manifests.pop("__cli_test_ext__", None)
        registry._manifests.pop("__cli_test_ext2__", None)


def test_extensions_inspect_known_extension() -> None:
    """'extensions inspect <name>' outputs JSON for a registered extension."""
    registry = get_extension_registry()
    registry.register(PluginManifest(name="__cli_test_ext__", version="5.0"))
    try:
        parser = build_parser()
        args = parser.parse_args(["extensions", "inspect", "__cli_test_ext__"])
        captured = StringIO()
        exit_code = 0
        with patch("sys.stdout", captured):
            try:
                handle_extensions(args)
            except SystemExit as exc:
                exit_code = exc.code if isinstance(exc.code, int) else 1
        assert exit_code == 0
        parsed = json.loads(captured.getvalue())
        assert parsed["name"] == "__cli_test_ext__"
        assert parsed["version"] == "5.0"
    finally:
        registry._manifests.pop("__cli_test_ext__", None)


def test_extensions_inspect_unknown_exits_nonzero() -> None:
    """'extensions inspect <unknown>' exits with non-zero code."""
    parser = build_parser()
    args = parser.parse_args(["extensions", "inspect", "no_such_extension"])
    with pytest.raises(SystemExit) as exc_info:
        handle_extensions(args)
    assert exc_info.value.code != 0
