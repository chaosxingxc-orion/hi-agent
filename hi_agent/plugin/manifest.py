"""PluginManifest: descriptor for a hi-agent plugin."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hi_agent.contracts.extension_manifest import ExtensionManifestMixin


@dataclass
class PluginManifest(ExtensionManifestMixin):
    """Descriptor for a plugin loaded into hi-agent.

    A plugin is a directory containing a ``plugin.json`` manifest and
    optional capability/skill/MCP definitions.

    Example ``plugin.json``::

        {
          "name": "research-tools",
          "version": "1.0.0",
          "description": "Web search and document extraction tools",
          "type": "capability",
          "capabilities": ["web_search", "web_extract"],
          "skill_dirs": ["skills/"],
          "mcp_servers": [],
          "entry_point": "plugin_entry.py"
        }
    """

    name: str
    version: str
    description: str = ""
    plugin_type: str = "capability"  # capability | skill | mcp | composite
    capabilities: list[str] = field(default_factory=list)
    skill_dirs: list[str] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    entry_point: str | None = None
    plugin_dir: str | None = None
    status: str = "loaded"  # loaded | active | inactive | error
    error: str | None = None

    # ExtensionManifest Protocol fields (Wave 10.5 W5-F)
    manifest_kind: str = "plugin"
    schema_version: int = 1
    posture_support: dict[str, bool] = field(
        default_factory=lambda: {"dev": True, "research": True, "prod": True}
    )
    required_posture: str = "any"
    tenant_scope: str = "tenant"
    dangerous_capabilities: list[str] = field(default_factory=list)
    config_schema: dict | None = None

    @classmethod
    def from_json(cls, path: str | Path) -> PluginManifest:
        """Load a PluginManifest from a plugin.json file.

        Args:
            path: Path to plugin.json.

        Returns:
            Parsed PluginManifest.

        Raises:
            ValueError: If required fields are missing.
            FileNotFoundError: If the file does not exist.
        """
        p = Path(path)
        with p.open(encoding="utf-8") as f:
            data = json.load(f)

        if "name" not in data:
            raise ValueError(f"Plugin manifest at {path} missing required field 'name'")
        if "version" not in data:
            raise ValueError(f"Plugin manifest at {path} missing required field 'version'")

        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            plugin_type=data.get("type", "capability"),
            capabilities=data.get("capabilities", []),
            skill_dirs=data.get("skill_dirs", []),
            mcp_servers=data.get("mcp_servers", []),
            entry_point=data.get("entry_point"),
            plugin_dir=str(p.parent),
            required_posture=data.get("required_posture", "any"),
            tenant_scope=data.get("tenant_scope", "tenant"),
            dangerous_capabilities=data.get("dangerous_capabilities", []),
            config_schema=data.get("config_schema", None),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "type": self.plugin_type,
            "capabilities": self.capabilities,
            "skill_dirs": self.skill_dirs,
            "mcp_servers": self.mcp_servers,
            "entry_point": self.entry_point,
            "plugin_dir": self.plugin_dir,
            "status": self.status,
        }

    def to_manifest_dict(self) -> dict[str, Any]:
        """Serialise to ExtensionManifest-compatible dict including enforcement fields."""
        d = self.to_dict()
        d.update(
            {
                "manifest_kind": self.manifest_kind,
                "schema_version": self.schema_version,
                "posture_support": self.posture_support,
                "required_posture": self.required_posture,
                "tenant_scope": self.tenant_scope,
                "dangerous_capabilities": self.dangerous_capabilities,
                "config_schema": self.config_schema,
            }
        )
        return d
