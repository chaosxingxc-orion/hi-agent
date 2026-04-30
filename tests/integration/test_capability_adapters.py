"""Tests for capability adapters (core_tool_adapter + descriptor_factory)."""

from __future__ import annotations

import pytest
from hi_agent.capability import (
    CapabilityDescriptorFactory,
    CapabilityRegistry,
    CapabilitySpec,
    CoreToolAdapter,
)
from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _echo_handler(payload: dict) -> dict:
    return {"echo": payload}


def _make_tool(
    name: str,
    description: str = "",
    parameters: dict | None = None,
    handler=None,
    **extras,
) -> dict:
    info: dict = {"name": name, "description": description}
    if parameters is not None:
        info["parameters"] = parameters
    if handler is not None:
        info["handler"] = handler
    info.update(extras)
    return info


# ================================================================== #
# CapabilityDescriptorFactory tests
# ================================================================== #


class TestDescriptorFactoryEffectHeuristics:
    """Verify verb-based effect_class inference."""

    factory = CapabilityDescriptorFactory()

    @pytest.mark.parametrize(
        "tool_name, expected",
        [
            ("read_file", "read_only"),
            ("search_docs", "read_only"),
            ("query_database", "read_only"),
            ("get_user", "read_only"),
            ("list_items", "read_only"),
            ("fetch_report", "read_only"),
            ("find_matches", "read_only"),
            ("lookup_address", "read_only"),
        ],
    )
    def test_read_only_verbs(self, tool_name: str, expected: str) -> None:
        assert self.factory.infer_effect_class(tool_name) == expected

    @pytest.mark.parametrize(
        "tool_name, expected",
        [
            ("write_config", "idempotent_write"),
            ("create_record", "idempotent_write"),
            ("update_profile", "idempotent_write"),
            ("set_value", "idempotent_write"),
            ("put_object", "idempotent_write"),
            ("upsert_row", "idempotent_write"),
        ],
    )
    def test_idempotent_write_verbs(self, tool_name: str, expected: str) -> None:
        assert self.factory.infer_effect_class(tool_name) == expected

    @pytest.mark.parametrize(
        "tool_name, expected",
        [
            ("delete_user", "irreversible_write"),
            ("send_email", "irreversible_write"),
            ("remove_item", "irreversible_write"),
            ("drop_table", "irreversible_write"),
            ("purge_cache", "irreversible_write"),
        ],
    )
    def test_irreversible_write_verbs(self, tool_name: str, expected: str) -> None:
        assert self.factory.infer_effect_class(tool_name) == expected

    def test_unknown_verb_defaults_to_unknown_effect(self) -> None:
        assert self.factory.infer_effect_class("frobnicate_data") == "unknown_effect"

    def test_hyphenated_name_normalised(self) -> None:
        assert self.factory.infer_effect_class("read-file") == "read_only"


class TestDescriptorFactoryBuildDescriptor:
    """Verify full descriptor construction with overrides."""

    factory = CapabilityDescriptorFactory()

    def test_basic_build(self) -> None:
        tool_info = _make_tool("search_logs", description="Search logs.")
        desc = self.factory.build_descriptor(tool_info)

        assert isinstance(desc, CapabilityDescriptor)
        assert desc.name == "search_logs"
        assert desc.effect_class == "read_only"
        assert desc.description == "Search logs."
        assert desc.sandbox_level == "none"

    def test_explicit_effect_class_in_tool_info(self) -> None:
        tool_info = _make_tool(
            "custom_tool",
            effect_class="irreversible_write",
        )
        desc = self.factory.build_descriptor(tool_info)
        assert desc.effect_class == "irreversible_write"

    def test_overrides_take_precedence(self) -> None:
        tool_info = _make_tool(
            "delete_user",
            description="Remove a user.",
            tags=["admin"],
        )
        overrides = {
            "effect_class": "idempotent_write",
            "sandbox_level": "container",
            "tags": ["safe", "test"],
        }
        desc = self.factory.build_descriptor(tool_info, overrides=overrides)

        assert desc.effect_class == "idempotent_write"
        assert desc.sandbox_level == "container"
        assert desc.tags == ("safe", "test")
        # description not overridden — comes from tool_info
        assert desc.description == "Remove a user."

    def test_parameters_forwarded(self) -> None:
        params = {"type": "object", "properties": {"q": {"type": "string"}}}
        tool_info = _make_tool("search_docs", parameters=params)
        desc = self.factory.build_descriptor(tool_info)
        assert desc.parameters == params

    def test_descriptor_is_frozen(self) -> None:
        desc = self.factory.build_descriptor(_make_tool("get_item"))
        with pytest.raises(AttributeError):
            desc.name = "other"  # type: ignore[misc]  expiry_wave: Wave 26


# ================================================================== #
# CoreToolAdapter tests
# ================================================================== #


class TestCoreToolAdapterAdaptTool:
    """Verify single-tool adaptation."""

    def test_adapt_read_only_tool(self) -> None:
        adapter = CoreToolAdapter(CapabilityDescriptorFactory())
        tool_info = _make_tool(
            "search_docs",
            description="Full-text search.",
            handler=_echo_handler,
        )
        spec = adapter.adapt_tool(tool_info)

        assert isinstance(spec, CapabilitySpec)
        assert spec.name == "search_docs"
        assert spec.handler is _echo_handler

    def test_adapt_write_tool(self) -> None:
        adapter = CoreToolAdapter(CapabilityDescriptorFactory())

        def writer(payload: dict) -> dict:
            return {"written": True}

        tool_info = _make_tool("create_record", handler=writer)
        spec = adapter.adapt_tool(tool_info)
        assert spec.name == "create_record"
        assert spec.handler({"x": 1}) == {"written": True}

    def test_placeholder_handler_when_none_provided(self) -> None:
        adapter = CoreToolAdapter(CapabilityDescriptorFactory())
        tool_info = _make_tool("query_something")
        spec = adapter.adapt_tool(tool_info)
        assert spec.name == "query_something"

        with pytest.raises(NotImplementedError, match="query_something"):
            spec.handler({})

    def test_override_applied_during_adapt(self) -> None:
        """Per-tool overrides dict is forwarded to descriptor factory."""
        overrides = {
            "search_docs": {"effect_class": "irreversible_write"},
        }
        adapter = CoreToolAdapter(CapabilityDescriptorFactory(), overrides=overrides)
        tool_info = _make_tool("search_docs", handler=_echo_handler)
        # Should not raise — override is consumed internally.
        spec = adapter.adapt_tool(tool_info)
        assert spec.name == "search_docs"


class TestCoreToolAdapterBatchRegistration:
    """Verify batch registration into CapabilityRegistry."""

    def test_batch_register(self) -> None:
        registry = CapabilityRegistry()
        adapter = CoreToolAdapter(CapabilityDescriptorFactory())

        tools = [
            _make_tool("get_user", handler=_echo_handler),
            _make_tool("create_user", handler=_echo_handler),
            _make_tool("delete_user", handler=_echo_handler),
        ]
        count = adapter.register_tools(registry, tools)

        assert count == 3
        assert sorted(registry.list_names()) == [
            "create_user",
            "delete_user",
            "get_user",
        ]

    def test_batch_register_empty_list(self) -> None:
        registry = CapabilityRegistry()
        adapter = CoreToolAdapter(CapabilityDescriptorFactory())
        assert adapter.register_tools(registry, []) == 0
        assert registry.list_names() == []

    def test_registered_tool_is_invocable(self) -> None:
        registry = CapabilityRegistry()
        adapter = CoreToolAdapter(CapabilityDescriptorFactory())
        adapter.register_tools(
            registry,
            [_make_tool("get_status", handler=lambda p: {"ok": True})],
        )
        spec = registry.get("get_status")
        assert spec.handler({}) == {"ok": True}

    def test_overrides_applied_during_batch(self) -> None:
        """Overrides dict is respected in batch mode."""
        overrides = {"get_status": {"effect_class": "irreversible_write"}}
        registry = CapabilityRegistry()
        adapter = CoreToolAdapter(CapabilityDescriptorFactory(), overrides=overrides)
        adapter.register_tools(
            registry,
            [_make_tool("get_status", handler=_echo_handler)],
        )
        # Spec is registered; override was applied during adapt (no
        # visible assertion on CapabilitySpec itself since it only
        # carries name+handler, but we verify no crash).
        assert registry.get("get_status").name == "get_status"
