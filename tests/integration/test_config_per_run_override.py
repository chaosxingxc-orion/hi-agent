# tests/test_config_per_run_override.py
import contextlib
from unittest.mock import MagicMock, patch

from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig


def test_resolve_with_patch_merges_correctly():
    """_resolve_with_patch merges patch over existing config."""
    cfg = TraceConfig(max_stages=10)
    builder = SystemBuilder(config=cfg)
    patched = builder._resolve_with_patch({"max_stages": 99})
    assert patched.max_stages == 99


def test_resolve_with_patch_does_not_mutate_original():
    """_resolve_with_patch does not mutate the builder's config."""
    cfg = TraceConfig(max_stages=10)
    builder = SystemBuilder(config=cfg)
    builder._resolve_with_patch({"max_stages": 99})
    assert builder._config.max_stages == 10  # unchanged


def test_resolve_with_patch_only_known_fields():
    """_resolve_with_patch ignores unknown fields."""
    cfg = TraceConfig()
    builder = SystemBuilder(config=cfg)
    patched = builder._resolve_with_patch({"unknown_field_xyz": "ignored", "max_stages": 5})
    assert patched.max_stages == 5
    assert not hasattr(patched, "unknown_field_xyz")


def test_build_executor_without_patch_uses_global():
    """Without patch, build_executor uses the global config."""
    cfg = TraceConfig(max_stages=7)
    builder = SystemBuilder(config=cfg)

    captured: list[TraceConfig] = []

    def mock_impl(self, contract, **kwargs):
        captured.append(self._config)
        raise RuntimeError("stop")

    with (
        patch.object(SystemBuilder, "_build_executor_impl", mock_impl),  # B1: SUT-internal mock — schedule replacement with boundary mock  # noqa: E501  # expiry_wave: Wave 27
        contextlib.suppress(RuntimeError),
    ):
        builder.build_executor(MagicMock())

    assert len(captured) == 1
    assert captured[0].max_stages == 7


def test_build_executor_with_patch_uses_patched_config():
    """With config_patch, build_executor creates a patched config."""
    cfg = TraceConfig(max_stages=7)
    builder = SystemBuilder(config=cfg)

    captured: list[TraceConfig] = []

    def mock_impl(self, contract, **kwargs):
        captured.append(self._config)
        raise RuntimeError("stop")

    with (
        patch.object(SystemBuilder, "_build_executor_impl", mock_impl),  # B1: SUT-internal mock — schedule replacement with boundary mock  # noqa: E501  # expiry_wave: Wave 27
        contextlib.suppress(RuntimeError),
    ):
        builder.build_executor(MagicMock(), config_patch={"max_stages": 99})

    assert len(captured) == 1
    assert captured[0].max_stages == 99
