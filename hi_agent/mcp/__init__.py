"""MCP (Model Context Protocol) integration layer for hi-agent.

This module provides:
- MCPRegistry: register and track MCP server connections
- MCPBinding: bind MCP tools to hi-agent's capability registry
- MCPHealth: health checking for registered MCP servers
"""

from hi_agent.mcp.registry import MCPRegistry
from hi_agent.mcp.binding import MCPBinding
from hi_agent.mcp.health import MCPHealth

__all__ = ["MCPRegistry", "MCPBinding", "MCPHealth"]
