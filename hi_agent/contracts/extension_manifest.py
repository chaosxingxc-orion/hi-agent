"""ExtensionManifest Protocol and ExtensionRegistry.

Defines a unified manifest shape that all 4 extension kinds implement:
  plugin | kernel | mcp_tool | knowledge

Rule 12 note: ExtensionRegistry is process-internal (not a persistent record);
no tenant_id field required.  # scope: process-internal — registry of in-process
extension descriptors; not persisted across restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class ExtensionManifest(Protocol):
    """Unified manifest protocol for all hi-agent extension kinds."""

    name: str
    version: str
    manifest_kind: str  # "plugin" | "kernel" | "mcp_tool" | "knowledge"
    schema_version: str
    posture_support: dict[str, bool]  # posture name -> supported

    def to_manifest_dict(self) -> dict:
        """Serialise to a JSON-compatible dict with at least name/version/kind keys."""
        ...


@dataclass
class ExtensionRegistry:
    """In-memory registry of ExtensionManifest instances.

    # scope: process-internal — not persisted; reconstructed on startup.
    """

    _registry: dict[str, ExtensionManifest] = field(default_factory=dict)

    def register(self, manifest: ExtensionManifest) -> None:
        """Register or replace a manifest by name."""
        self._registry[manifest.name] = manifest

    def lookup(self, name: str) -> ExtensionManifest | None:
        """Return the manifest registered under *name*, or None."""
        return self._registry.get(name)

    def list_by_kind(self, kind: str) -> list[ExtensionManifest]:
        """Return all manifests with manifest_kind == *kind*."""
        return [m for m in self._registry.values() if m.manifest_kind == kind]

    def list_for_posture(self, posture_name: str) -> list[ExtensionManifest]:
        """Return manifests whose posture_support[posture_name] is True."""
        return [
            m for m in self._registry.values() if m.posture_support.get(posture_name, False)
        ]

    def list_all(self) -> list[ExtensionManifest]:
        """Return all registered manifests."""
        return list(self._registry.values())


_global_registry = ExtensionRegistry()


def get_extension_registry() -> ExtensionRegistry:
    """Return the process-global ExtensionRegistry singleton."""
    return _global_registry
