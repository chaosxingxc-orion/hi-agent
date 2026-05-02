"""McpToolManifest — implements the ExtensionManifest protocol for MCP tool sets.

Wraps MCP tool descriptors into the unified ExtensionManifest shape consumed by
ExtensionRegistry and the /manifest endpoint.

# scope: process-internal — not a persistent record; no tenant_id required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hi_agent.contracts.extension_manifest import ExtensionManifestMixin


# W31 T-24' decision: platform manifest; tenant-agnostic.
# scope: process-internal
@dataclass
class McpToolManifest(ExtensionManifestMixin):
    """Unified manifest descriptor for an MCP tool set.

    Implements the ExtensionManifest protocol so it can be registered in
    ExtensionRegistry and surfaced through GET /manifest.
    """

    name: str
    version: str = "1.0"
    schema_version: int = 1
    manifest_kind: str = "mcp_tool"
    posture_support: dict[str, bool] = field(
        default_factory=lambda: {"dev": True, "research": True, "prod": True}
    )
    tools: list[str] = field(default_factory=list)
    required_posture: str = "any"
    tenant_scope: str = "global"
    dangerous_capabilities: list[str] = field(default_factory=list)
    config_schema: dict | None = None

    def to_manifest_dict(self) -> dict:
        """Return JSON-compatible dict with at least name, version, kind keys."""
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.manifest_kind,
            "schema_version": self.schema_version,
            "tools": self.tools,
            "posture_support": self.posture_support,
            "required_posture": self.required_posture,
            "tenant_scope": self.tenant_scope,
            "dangerous_capabilities": self.dangerous_capabilities,
            "config_schema": self.config_schema,
        }
