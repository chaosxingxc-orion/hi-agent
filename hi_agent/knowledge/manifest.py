"""KnowledgeManifest — implements the ExtensionManifest protocol for knowledge backends.

Wraps knowledge backend descriptors into the unified ExtensionManifest shape consumed
by ExtensionRegistry and the /manifest endpoint.

# scope: process-internal — not a persistent record; no tenant_id required.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeManifest:
    """Unified manifest descriptor for a knowledge backend.

    Implements the ExtensionManifest protocol so it can be registered in
    ExtensionRegistry and surfaced through GET /manifest.
    """

    name: str
    version: str = "1.0"
    schema_version: str = "1.0"
    manifest_kind: str = "knowledge"
    posture_support: dict[str, bool] = field(
        default_factory=lambda: {"dev": True, "research": True, "prod": True}
    )
    backends: list[str] = field(default_factory=list)

    def to_manifest_dict(self) -> dict:
        """Return JSON-compatible dict with at least name, version, kind keys."""
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.manifest_kind,
            "schema_version": self.schema_version,
            "backends": self.backends,
            "posture_support": self.posture_support,
        }
