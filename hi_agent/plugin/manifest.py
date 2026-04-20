"""PluginManifest: descriptor for a hi-agent plugin."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginManifest:
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
