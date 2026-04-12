"""MCPHealth: health checking for registered MCP servers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPHealth:
    """Health checker for MCP server connections.

    Probes each registered MCP server and updates its status in the
    MCPRegistry.  Designed to be called periodically or on demand.
    """

    def __init__(self, mcp_registry: Any) -> None:
        """Initialize with an MCPRegistry.

        Args:
            mcp_registry: MCPRegistry instance to check.
        """
        self._registry = mcp_registry

    def check_all(self) -> dict[str, str]:
        """Probe all registered MCP servers and return their statuses.

        Returns:
            Dict mapping server_id → status ("healthy" | "error" | "timeout").
        """
        results: dict[str, str] = {}
        for server in self._registry.list_servers():
            server_id = server["server_id"]
            status = self._check_one(server)
            self._registry.update_status(server_id, status)
            results[server_id] = status
        return results

    def _check_one(self, server: dict[str, Any]) -> str:
        """Probe a single server entry.

        Currently a stub that returns 'registered' since no transport is
        wired.  Real implementations should ping the endpoint.
        """
        # TODO: implement actual transport-level ping when transports are wired.
        return server.get("status", "registered")

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a health snapshot of all servers."""
        return self._registry.list_servers()
