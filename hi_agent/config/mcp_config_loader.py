"""Load MCP server registrations from config/mcp_servers.json into MCPRegistry."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.mcp.registry import MCPRegistry

logger = logging.getLogger(__name__)

_DEFAULT_MCP_JSON = Path(__file__).parent.parent.parent / "config" / "mcp_servers.json"

_VALID_TRANSPORTS = frozenset({"stdio", "http", "sse"})


class McpConfigError(ValueError):
    """Raised when mcp_servers.json contains invalid entries."""


def load_mcp_servers_from_config(
    registry: MCPRegistry,
    *,
    config_path: Path | str | None = None,
    existing_names: set[str] | None = None,
) -> int:
    """Load MCP server specs from config_path into registry.

    Returns count of servers registered.
    existing_names: set of server names already registered (from plugins); top-level config
    wins on conflict — conflicting plugin entry is logged at WARNING.
    """
    path = Path(config_path) if config_path is not None else _DEFAULT_MCP_JSON
    if not path.exists():
        return 0

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"mcp_servers.json is not valid JSON: {exc}") from exc

    servers = raw.get("servers", [])
    if not isinstance(servers, list):
        raise McpConfigError("mcp_servers.json: 'servers' must be a list")

    known = set(existing_names or [])
    errors: list[str] = []
    registered = 0

    for i, srv in enumerate(servers):
        try:
            n = _register_one_server(registry, srv, index=i, known=known)
            if n:
                known.add(n)
                registered += 1
        except McpConfigError as exc:
            errors.append(str(exc))

    if errors:
        raise McpConfigError(
            f"mcp_servers.json has {len(errors)} invalid entry(s):\n" + "\n".join(errors)
        )

    logger.info(
        "load_mcp_servers_from_config: registered %d MCP server(s) from %s.", registered, path
    )
    return registered


def _register_one_server(
    registry: MCPRegistry,
    srv: Any,
    *,
    index: int,
    known: set[str],
) -> str | None:
    """Validate and register a single server spec. Returns the server name on success."""
    if not isinstance(srv, dict):
        raise McpConfigError(f"servers[{index}]: must be a dict")
    name = srv.get("name")
    if not name or not isinstance(name, str):
        raise McpConfigError(f"servers[{index}]: 'name' is required and must be a string")
    transport = srv.get("transport", "stdio")
    if transport not in _VALID_TRANSPORTS:
        raise McpConfigError(
            f"servers[{index}] ({name!r}): transport must be one of {sorted(_VALID_TRANSPORTS)}"
        )
    if name in known:
        logger.warning(
            "load_mcp_servers_from_config: server %r already registered by plugin; "
            "top-level mcp_servers.json entry wins.",
            name,
        )
    server_id = srv.get("id", f"config:{name}")
    endpoint = srv.get("endpoint", srv.get("command", ""))
    tools_filter = srv.get("tools_filter")
    registry.register(
        server_id=server_id,
        name=name,
        transport=transport,
        endpoint=endpoint,
        tools=tools_filter,
    )
    return name
