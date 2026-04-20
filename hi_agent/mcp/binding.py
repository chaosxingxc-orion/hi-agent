"""MCPBinding: bind MCP server tools into hi-agent's capability registry.

Transport availability policy — Path A: Deferred
--------------------------------------------------
MCP transport is **Path A — Deferred**.  When no transport is configured,
tools are enumerated from the MCP registry and tracked in ``_unavailable``
but are NOT registered to CapabilityRegistry.  Upper-layer agents should
use provider adapters as the primary integration path.  To enable MCP
tools, pass a real transport instance:
``MCPBinding(registry, mcp_registry, transport=YourTransport())``.

This prevents the old behaviour where broken stubs were silently registered
as if they were runtime-usable.

To add real transport support:

1. Implement an ``MCPTransport`` class with
   ``invoke(server_id, tool_name, payload) -> dict``.
2. Pass the transport instance to ``MCPBinding.__init__``.
3. ``bind_all()`` will now register working handlers.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MCP_UNAVAILABLE_MSG = (
    "MCP transport not configured — use provider adapters or pass transport= "
    "to MCPBinding to enable MCP tools."
)


class MCPBinding:
    """Bind tools from registered MCP servers into a CapabilityRegistry.

    Only tools that have a live transport are registered as invokable
    capabilities.  Tools without transport are tracked separately so the
    manifest can report them as ``available=False``.
    """

    def __init__(self, registry: Any, mcp_registry: Any, transport: Any = None) -> None:
        """Initialize with a CapabilityRegistry, MCPRegistry, and optional transport.

        Args:
            registry: hi-agent CapabilityRegistry instance.
            mcp_registry: MCPRegistry instance to source tools from.
            transport: Optional MCPTransport.  When None, tools are NOT
                registered as invokable capabilities.
        """
        self._registry = registry
        self._mcp_registry = mcp_registry
        self._transport = transport
        # Tracks tools that exist in registered servers but have no transport.
        self._unavailable: list[str] = []

    def bind_all(self) -> int:
        """Bind all tools from all registered healthy MCP servers.

        When transport has list_tools(), performs dynamic discovery:
        1. Health check must pass (server status == "healthy")
        2. Call transport.list_tools(server_id)
        3. Merge with manifest pre-claims (_merge_tools)
        4. Register final tool set to CapabilityRegistry

        Falls back to manifest pre-claims on discovery failure (degraded mode).
        When no transport, tools are tracked in _unavailable (Path A deferred).

        Returns:
            Number of tools successfully bound (0 when no transport).
        """
        self._unavailable.clear()
        self._warnings: list[str] = []

        if self._transport is None:
            # Enumerate tools for discovery purposes but do NOT register them.
            # Include ALL servers regardless of status — every declared tool is
            # unavailable when there is no transport, including errored ones.
            for server in self._mcp_registry.list_servers():
                server_id = server["server_id"]
                for tool_name in server.get("tools", []):
                    cap_name = f"mcp.{server_id}.{tool_name}"
                    self._unavailable.append(cap_name)
            if self._unavailable:
                logger.info(
                    "MCPBinding.bind_all: transport not configured — %d MCP tool(s) are "
                    "known but NOT registered as capabilities: %s. "
                    "Provide an MCPTransport to enable invocation.",
                    len(self._unavailable),
                    self._unavailable,
                )
            return 0

        from hi_agent.capability.registry import CapabilitySpec

        bound = 0
        has_list_tools = hasattr(self._transport, "list_tools")

        for server in self._mcp_registry.list_servers():
            server_id = server["server_id"]
            status = server["status"]

            if status != "healthy":
                if status == "registered":
                    for tool_name in server.get("tools", []):
                        self._unavailable.append(f"mcp.{server_id}.{tool_name}")
                logger.debug(
                    "MCPBinding.bind_all: skipping server %r (status=%r)", server_id, status
                )
                continue

            preclaimed = server.get("tools", [])

            if has_list_tools:
                # Dynamic discovery — wins over manifest pre-claims
                try:
                    discovered = self._transport.list_tools(server_id)
                    final_tools, warnings = self._merge_tools(server_id, preclaimed, discovered)
                    self._warnings.extend(warnings)
                    for w in warnings:
                        logger.warning("MCPBinding: %s", w)
                except Exception as exc:
                    # Discovery failed → fall back to manifest pre-claims (degraded)
                    logger.warning(
                        "MCPBinding.bind_all: tools/list failed for %r (%s) — "
                        "falling back to manifest pre-claims",
                        server_id,
                        exc,
                    )
                    final_tools = list(preclaimed)
                    self._warnings.append(
                        f"MCP server {server_id!r}: tools/list failed ({exc}), "
                        f"using manifest pre-claims (degraded)"
                    )
            else:
                final_tools = list(preclaimed)

            for tool_name in final_tools:
                cap_name = f"mcp.{server_id}.{tool_name}"
                handler = self._make_handler(server_id, tool_name)
                spec = CapabilitySpec(name=cap_name, handler=handler)
                self._registry.register(spec)
                bound += 1
                logger.debug("MCPBinding.bind_all: bound %r", cap_name)

        logger.info("MCPBinding.bind_all: bound %d MCP tools.", bound)
        return bound

    @staticmethod
    def _merge_tools(
        server_id: str,
        preclaimed: list[str],
        discovered: list[dict],
    ) -> tuple[list[str], list[str]]:
        """Merge preclaimed (manifest) and dynamically discovered tools.

        Merge strategy:
        1. Dynamic discovery wins — use discovered tool names as the final set.
        2. Discovered-only tools: register without warning.
        3. Manifest-only tools (declared but not found): emit warning.
        4. Both agree: use discovered.

        Returns:
            (final_tool_names, warnings)
            warnings: list of human-readable warning strings.
        """
        discovered_names = {t["name"] for t in discovered}
        preclaimed_set = set(preclaimed)

        warnings: list[str] = []
        manifest_only = preclaimed_set - discovered_names
        for tool_name in sorted(manifest_only):
            warnings.append(
                f"MCP server {server_id!r}: tool {tool_name!r} declared in manifest "
                f"but not found in tools/list response"
            )

        return sorted(discovered_names), warnings

    def list_warnings(self) -> list[str]:
        """Return merge warnings from last bind_all() call.

        Returns an empty list if bind_all() has not been called yet.
        """
        return list(getattr(self, "_warnings", []))

    def list_unavailable(self) -> list[str]:
        """Return capability names that exist but have no transport.

        Populated after ``bind_all()`` is called without a transport.
        """
        return list(self._unavailable)

    def _make_handler(self, server_id: str, tool_name: str):
        """Return a capability handler that forwards calls to the MCP transport."""
        transport = self._transport

        def handler(payload: dict) -> dict:
            return transport.invoke(server_id, tool_name, payload)

        handler.__name__ = f"mcp_{server_id}_{tool_name}"
        return handler
