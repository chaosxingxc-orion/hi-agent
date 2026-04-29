"""MCPHealth: health checking for registered MCP servers.

When a ``StdioMCPTransport`` (or compatible transport with a ``ping()``
method) is passed, ``check_all()`` performs a live JSON-RPC initialize
handshake to verify each server is reachable.  When no transport is
provided, the last recorded registry status is returned unchanged.
"""

from __future__ import annotations

import contextlib
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
            Dict mapping server_id → status ("healthy" | "degraded" | "unhealthy" | "error").
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

        Status values:
        - "healthy": live ping succeeded, no stderr error keywords detected
        - "degraded": ping succeeded but stderr contains error keywords
        - "unhealthy": subprocess crash or ping failed
        - "error": backward-compat alias returned from the no-transport path
          when the last recorded status is "error"

        Without a transport, returns the last recorded registry status
        so downstream callers have a stable, non-empty value.
        """
        if self._transport is None or not hasattr(self._transport, "ping"):
            # No transport — return last recorded status unchanged.
            return server.get("status", "registered")

        server_id = server.get("server_id")
        try:
            # Prefer per-server ping (MultiStdioTransport accepts server_id);
            # fall back to no-arg ping for single-server transports.
            try:
                alive = self._transport.ping(server_id)
            except TypeError:
                alive = self._transport.ping()
        except Exception as exc:
            logger.warning(
                "MCPHealth._check_one: ping failed for server=%r: %s",
                server_id,
                exc,
            )
            return "unhealthy"

        if not alive:
            return "unhealthy"

        # Ping succeeded — check stderr for degradation signals.
        # get_stderr_tail() holds per-transport stderr (StdioMCPTransport) or
        # may accept server_id (MultiStdioTransport).  Try no-arg first, then
        # with server_id as fallback.
        stderr_tail: list[str] = []
        if hasattr(self._transport, "get_stderr_tail"):
            try:
                stderr_tail = self._transport.get_stderr_tail()
            except TypeError:
                with contextlib.suppress(Exception):  # rule7-exempt:  expiry_wave: Wave 22
                    stderr_tail = self._transport.get_stderr_tail(server_id)
            except Exception:  # rule7-exempt: expiry_wave="Wave 22" replacement_test: wave22-tests
                pass

        error_keywords = ("error", "exception", "traceback", "fatal", "critical")
        has_stderr_errors = False
        if isinstance(stderr_tail, list):
            has_stderr_errors = any(
                isinstance(line, str) and any(kw in line.lower() for kw in error_keywords)
                for line in stderr_tail
            )
        if has_stderr_errors:
            logger.debug(
                "MCPHealth._check_one: server=%r degraded (stderr errors detected)",
                server_id,
            )
            return "degraded"

        logger.debug("MCPHealth._check_one: server=%r healthy", server_id)
        return "healthy"

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a health snapshot of all servers."""
        return self._registry.list_servers()
