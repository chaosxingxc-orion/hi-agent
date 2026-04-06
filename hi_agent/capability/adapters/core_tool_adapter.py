"""Adapts agent-core tool definitions to hi-agent CapabilitySpec.

This module converts dict-based tool information (matching the shape
produced by agent-core's ``ToolInfo``) into ``CapabilitySpec`` instances
that can be registered in ``CapabilityRegistry``.

No direct import of the ``openjiuwen`` package is required — the adapter
operates entirely on plain dicts so it works even when agent-core is not
installed.
"""

from __future__ import annotations

from collections.abc import Callable

from hi_agent.capability.adapters.descriptor_factory import (
    CapabilityDescriptorFactory,
)
from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec


def _make_placeholder_handler(tool_name: str) -> Callable[[dict], dict]:
    """Return a handler that raises when invoked without a real backend.

    This is used when a tool_info dict does not carry an executable
    handler — the capability is registered for metadata / routing
    purposes but cannot be called until a real handler is attached.
    """

    def _placeholder(payload: dict) -> dict:
        raise NotImplementedError(
            f"Tool {tool_name!r} has no executable handler attached. "
            "Provide a handler via tool_info['handler'] or replace after "
            "registration."
        )

    return _placeholder


class CoreToolAdapter:
    """Adapts agent-core tool definitions to hi-agent CapabilitySpec.

    Usage::

        adapter = CoreToolAdapter()
        spec = adapter.adapt_tool({
            "name": "search_docs",
            "description": "Full-text search over docs.",
            "parameters": {"type": "object", "properties": {...}},
        })
        registry.register(spec)

    Or batch::

        count = adapter.register_tools(registry, [tool1, tool2, ...])
    """

    def __init__(
        self,
        descriptor_factory: CapabilityDescriptorFactory | None = None,
        overrides: dict[str, dict] | None = None,
    ) -> None:
        """Initialise the adapter.

        Args:
            descriptor_factory: Factory used to build rich descriptors.
                Defaults to a vanilla ``CapabilityDescriptorFactory``.
            overrides: Mapping of ``tool_name -> override_dict`` applied
                when building descriptors.  This is the "capability
                overrides YAML" concept expressed as a simple dict.
        """
        self._factory = descriptor_factory or CapabilityDescriptorFactory()
        self._overrides: dict[str, dict] = overrides or {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def adapt_tool(self, tool_info: dict) -> CapabilitySpec:
        """Convert a tool definition dict to ``CapabilitySpec``.

        ``tool_info`` keys:

        * **name** (str, required): Canonical tool name.
        * **description** (str, optional): Human-readable summary.
        * **parameters** (dict, optional): JSON-schema of accepted args.
        * **effect_class** (str, optional): Explicit effect class.
        * **tags** (list[str], optional): Classification tags.
        * **handler** (callable, optional): ``(dict) -> dict`` handler.
          When absent a placeholder that raises ``NotImplementedError``
          is used.

        Returns:
            A ``CapabilitySpec`` ready for ``CapabilityRegistry.register``.
        """
        name: str = tool_info["name"]
        handler = tool_info.get("handler", _make_placeholder_handler(name))

        # Build the rich descriptor (stored as metadata but not yet
        # surfaced on CapabilitySpec — kept for future enrichment).
        per_tool_overrides = self._overrides.get(name)
        self._factory.build_descriptor(tool_info, overrides=per_tool_overrides)

        return CapabilitySpec(name=name, handler=handler)

    def register_tools(
        self,
        registry: CapabilityRegistry,
        tools: list[dict],
    ) -> int:
        """Batch register tools into a ``CapabilityRegistry``.

        Returns:
            Number of capabilities successfully registered.
        """
        count = 0
        for tool_info in tools:
            spec = self.adapt_tool(tool_info)
            registry.register(spec)
            count += 1
        return count
