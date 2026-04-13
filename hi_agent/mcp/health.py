"""MCPHealth: health checking for registered MCP servers.

When a ``StdioMCPTransport`` (or compatible transport with a ``ping()``
method) is passed, ``check_all()`` performs a live JSON-RPC initialize
handshake to verify each server is reachable.  When no transport is
provided, the last recorded registry status is returned unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPHealth:
    """Health checker for MCP server connections.

    Probes each registered MCP server and updates its status in the
    MCPRegistry.  Designed to be called periodically or on demand.

    Args:
        mcp_registry: MCPRegistry instance to check.
        transport: Optional transport with a ``ping()`` method.  When
            provided, a live handshake is performed; otherwise the last
            known registry status is returned as-is.
    """

    def __init__(self, mcp_registry: Any, transport: Any = None) -> None:
        self._registry = mcp_registry
        self._transport = transport

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
        """Return health status for *server*.

        When a transport is configured and exposes ``ping()``, sends a
        live JSON-RPC initialize handshake.  On success returns "healthy";
        on failure returns "error".

        Without a transport, returns the last recorded registry status
        so downstream callers have a stable, non-empty value.
        """
        if self._transport is not None and hasattr(self._transport, "ping"):
            try:
                alive = self._transport.ping()
                status = "healthy" if alive else "error"
                logger.debug(
                    "MCPHealth._check_one: server=%r ping=%s status=%s",
                    server.get("server_id"),
                    alive,
                    status,
                )
                return status
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MCPHealth._check_one: ping failed for server=%r: %s",
                    server.get("server_id"),
                    exc,
                )
                return "error"
        # No transport — return last recorded status unchanged.
        return server.get("status", "registered")

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a health snapshot of all servers."""
        return self._registry.list_servers()
