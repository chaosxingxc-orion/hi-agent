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

        MCP transport is **Path A — Deferred**.  When no transport is
        configured, tools are enumerated from the MCP registry and tracked in
        ``_unavailable`` but are NOT registered to CapabilityRegistry.
        Upper-layer agents should use provider adapters as the primary
        integration path.  To enable MCP tools, pass a real transport
        instance: ``MCPBinding(registry, mcp_registry, transport=YourTransport())``.

        Returns:
            Number of tools successfully bound (0 when no transport).
        """
        self._unavailable.clear()

        if self._transport is None:
            # Enumerate tools for discovery purposes but do NOT register them.
            for server in self._mcp_registry.list_servers():
                server_id = server["server_id"]
                if server["status"] not in ("registered", "healthy"):
                    continue
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

        from hi_agent.capability.registry import CapabilitySpec  # noqa: PLC0415

        bound = 0
        for server in self._mcp_registry.list_servers():
            server_id = server["server_id"]
            status = server["status"]
            if status == "healthy":
                for tool_name in server.get("tools", []):
                    cap_name = f"mcp.{server_id}.{tool_name}"
                    handler = self._make_handler(server_id, tool_name)
                    spec = CapabilitySpec(name=cap_name, handler=handler)
                    self._registry.register(spec)
                    bound += 1
                    logger.debug("MCPBinding.bind_all: bound %r", cap_name)
            elif status == "registered":
                # Declared but not yet health-checked — track as unavailable,
                # do NOT register as a callable capability.
                for tool_name in server.get("tools", []):
                    cap_name = f"mcp.{server_id}.{tool_name}"
                    self._unavailable.append(cap_name)
                logger.info(
                    "MCPBinding.bind_all: server %r is unverified (status=%r) — "
                    "%d tool(s) tracked as unavailable, not registered.",
                    server_id,
                    status,
                    len(server.get("tools", [])),
                )
            else:
                logger.debug(
                    "MCPBinding.bind_all: skipping server %r (status=%r)",
                    server_id,
                    status,
                )
        logger.info("MCPBinding.bind_all: bound %d MCP tools.", bound)
        return bound

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
