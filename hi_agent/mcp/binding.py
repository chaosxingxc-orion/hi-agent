"""MCPBinding: bind MCP server tools into hi-agent's capability registry."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPBinding:
    """Bind tools from registered MCP servers into a CapabilityRegistry.

    Each MCP tool becomes a named capability that the capability invoker
    can call.  The binding creates a closure that delegates invocation to
    the MCP server's transport.
    """

    def __init__(self, registry: Any, mcp_registry: Any) -> None:
        """Initialize with a CapabilityRegistry and MCPRegistry.

        Args:
            registry: hi-agent CapabilityRegistry instance.
            mcp_registry: MCPRegistry instance to source tools from.
        """
        self._registry = registry
        self._mcp_registry = mcp_registry

    def bind_all(self) -> int:
        """Bind all tools from all registered healthy MCP servers.

        Returns:
            Number of tools successfully bound.
        """
        from hi_agent.capability.registry import CapabilitySpec  # noqa: PLC0415

        bound = 0
        for server in self._mcp_registry.list_servers():
            server_id = server["server_id"]
            if server["status"] not in ("registered", "healthy"):
                logger.debug("MCPBinding.bind_all: skipping server %r (status=%r)", server_id, server["status"])
                continue
            for tool_name in server.get("tools", []):
                cap_name = f"mcp.{server_id}.{tool_name}"
                handler = self._make_handler(server_id, tool_name)
                spec = CapabilitySpec(name=cap_name, handler=handler)
                self._registry.register(spec)
                bound += 1
                logger.debug("MCPBinding.bind_all: bound %r", cap_name)
        logger.info("MCPBinding.bind_all: bound %d MCP tools.", bound)
        return bound

    def _make_handler(self, server_id: str, tool_name: str):
        """Return a capability handler that forwards calls to the MCP tool."""

        def handler(payload: dict) -> dict:
            # Placeholder: real implementation would invoke the MCP transport.
            # This stub returns a structured response so the pipeline does not crash
            # before a real MCP transport is wired.
            logger.warning(
                "MCPBinding: MCP tool %r on server %r called but no transport is wired. "
                "Register an MCP transport to enable real invocations.",
                tool_name,
                server_id,
            )
            return {
                "success": False,
                "error": f"MCP tool {tool_name!r} on server {server_id!r}: transport not configured",
                "score": 0.0,
            }

        handler.__name__ = f"mcp_{server_id}_{tool_name}"
        return handler
