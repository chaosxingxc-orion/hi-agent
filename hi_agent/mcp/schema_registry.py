"""MCP tool schema version registry (HI-W10-005).

Tracks the tool schemas returned by MCP servers and emits warnings when
schemas drift (tools added, removed, or parameter shapes changed).
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


def _schema_fingerprint(tools: list[dict]) -> str:
    """Stable fingerprint for a tool list (sorted by name)."""
    normalised = sorted(tools, key=lambda t: t.get("name", ""))
    return hashlib.sha256(json.dumps(normalised, sort_keys=True).encode()).hexdigest()[:16]


class MCPSchemaRegistry:
    """Records tool schema snapshots per server_id and warns on drift.

    Usage::

        registry = MCPSchemaRegistry()
        # After tools/list call:
        registry.record(server_id, tools)   # first call — just stores
        registry.record(server_id, tools)   # subsequent — warns if drifted
    """

    def __init__(self) -> None:
        # server_id -> {"fingerprint": str, "tools": list[dict]}
        self._snapshots: dict[str, dict] = {}

    def record(self, server_id: str, tools: list[dict]) -> bool:
        """Store tools snapshot; return True if schema drifted since last record.

        Emits a WARNING log when drift is detected.  The caller can use the
        return value to take additional action (e.g. trigger re-discovery).
        """
        fingerprint = _schema_fingerprint(tools)
        prev = self._snapshots.get(server_id)
        self._snapshots[server_id] = {"fingerprint": fingerprint, "tools": list(tools)}
        if prev is None:
            logger.debug(
                "MCPSchemaRegistry: recorded initial schema for %r (%d tools, fp=%s)",
                server_id,
                len(tools),
                fingerprint,
            )
            return False

        if prev["fingerprint"] == fingerprint:
            return False

        # Drift detected — compute diff for log message
        prev_names = {t.get("name") for t in prev["tools"]}
        curr_names = {t.get("name") for t in tools}
        added = curr_names - prev_names
        removed = prev_names - curr_names
        logger.warning(
            "MCPSchemaRegistry: schema drift for server %r "
            "(fp %s → %s; +%d tools: %s; -%d tools: %s)",
            server_id,
            prev["fingerprint"],
            fingerprint,
            len(added),
            sorted(added),
            len(removed),
            sorted(removed),
        )
        return True

    def get_fingerprint(self, server_id: str) -> str | None:
        """Return the last recorded fingerprint for a server, or None."""
        snap = self._snapshots.get(server_id)
        return snap["fingerprint"] if snap else None

    def get_tools(self, server_id: str) -> list[dict] | None:
        """Return the last recorded tool list for a server, or None."""
        snap = self._snapshots.get(server_id)
        return list(snap["tools"]) if snap else None

    def all_servers(self) -> list[str]:
        """Return list of all tracked server IDs."""
        return sorted(self._snapshots.keys())
