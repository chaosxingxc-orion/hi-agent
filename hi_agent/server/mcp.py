"""MCP (Model Context Protocol) server — JSON-RPC 2.0 over HTTP.

Exposes hi-agent's CapabilityRegistry as an MCP-compatible tool server.
Implements the minimum viable MCP surface:
  - tools/list  → enumerate available tools with schemas
  - tools/call  → invoke a tool by name with arguments
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPServer:
    """Bridges CapabilityRegistry to MCP protocol.

    This is a server-side MCP implementation: it receives tool list/call
    requests from MCP clients (e.g., Claude Desktop, other LLM clients)
    and dispatches them to hi-agent's CapabilityInvoker.
    """

    def __init__(self, registry: Any, invoker: Any) -> None:
        """Args:
        registry: CapabilityRegistry — source of truth for tool schemas.
        invoker: CapabilityInvoker — used to execute tool calls.
        """
        self._registry = registry
        self._invoker = invoker

    def list_tools(self) -> dict:
        """MCP tools/list response.

        Returns a dict compatible with MCP protocol:
        {"tools": [{"name": str, "description": str, "inputSchema": {...}}]}
        """
        tools = []
        for name in self._registry.list_names():
            spec = self._registry.get(name)
            tools.append(
                {
                    "name": name,
                    "description": getattr(spec, "description", ""),
                    "inputSchema": getattr(
                        spec, "parameters", {"type": "object", "properties": {}}
                    ),
                }
            )
        return {"tools": tools}

    def call_tool(self, name: str, arguments: dict) -> dict:
        """MCP tools/call response.

        Invokes the named tool with the given arguments and returns
        an MCP-compatible content response.

        Returns:
            {"content": [{"type": "text", "text": str}], "isError": bool}
        """
        try:
            result = self._invoker.invoke(name, arguments)
            text = json.dumps(result, ensure_ascii=False, default=str)
            return {
                "content": [{"type": "text", "text": text}],
                "isError": not result.get("success", True),
            }
        except KeyError:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name!r}"}],
                "isError": True,
            }
        except Exception as exc:
            logger.exception("MCP tool call failed: %s", name)
            return {
                "content": [{"type": "text", "text": f"Tool execution error: {exc}"}],
                "isError": True,
            }
