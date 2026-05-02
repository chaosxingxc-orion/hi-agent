"""MCPRegistry: register, manage, and track MCP server connections."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# W31 T-7' decision: platform MCP servers are tenant-agnostic.  An MCP server
# endpoint (a stdio process or HTTP URL) is registered once at the platform
# level and shared across all tenants; per-tenant restriction or proxying lives
# above this layer (route handlers / policy gates / posture flags), not on the
# registry row.
# scope: process-internal
@dataclass
class MCPServerEntry:
    """Registered MCP server metadata."""

    server_id: str
    name: str
    transport: str  # "stdio" | "http" | "sse"
    endpoint: str  # command string or URL
    tools: list[str] = field(default_factory=list)
    status: str = "registered"  # registered | healthy | degraded | error
    error: str | None = None


class MCPRegistry:
    """Registry for MCP server connections.

    Thread-safe registry that tracks registered MCP servers and their
    discovered tools. Acts as the authoritative source for which MCP
    capabilities are available at runtime.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._servers: dict[str, MCPServerEntry] = {}
        self._lock = threading.Lock()

    def register(
        self,
        server_id: str,
        name: str,
        transport: str,
        endpoint: str,
        tools: list[str] | None = None,
    ) -> MCPServerEntry:
        """Register an MCP server.

        Args:
            server_id: Unique identifier for this server.
            name: Human-readable server name.
            transport: Transport type: "stdio", "http", or "sse".
            endpoint: Command (stdio) or URL (http/sse) to connect to.
            tools: Optional pre-declared tool names (discovered lazily if omitted).

        Returns:
            The registered MCPServerEntry.
        """
        entry = MCPServerEntry(
            server_id=server_id,
            name=name,
            transport=transport,
            endpoint=endpoint,
            tools=tools or [],
        )
        with self._lock:
            self._servers[server_id] = entry
        logger.info("MCPRegistry.register: server_id=%r, transport=%r", server_id, transport)
        return entry

    def deregister(self, server_id: str) -> bool:
        """Remove an MCP server from the registry.

        Returns True if the server was found and removed.
        """
        with self._lock:
            removed = self._servers.pop(server_id, None)
        if removed:
            logger.info("MCPRegistry.deregister: removed server_id=%r", server_id)
        return removed is not None

    def get(self, server_id: str) -> MCPServerEntry | None:
        """Get a server entry by ID, or None if not found."""
        with self._lock:
            return self._servers.get(server_id)

    def list_servers(self) -> list[dict[str, Any]]:
        """Return a list of all registered servers as serialisable dicts."""
        with self._lock:
            return [
                {
                    "server_id": e.server_id,
                    "name": e.name,
                    "transport": e.transport,
                    "endpoint": e.endpoint,
                    "tools": e.tools,
                    "status": e.status,
                }
                for e in self._servers.values()
            ]

    def update_status(self, server_id: str, status: str, error: str | None = None) -> None:
        """Update the health status of a registered server."""
        with self._lock:
            entry = self._servers.get(server_id)
            if entry is not None:
                entry.status = status
                entry.error = error

    def update_tools(self, server_id: str, tools: list[str]) -> None:
        """Update the discovered tool list for a registered server."""
        with self._lock:
            entry = self._servers.get(server_id)
            if entry is not None:
                entry.tools = tools

    def __len__(self) -> int:
        """Return the number of registered servers."""
        with self._lock:
            return len(self._servers)
