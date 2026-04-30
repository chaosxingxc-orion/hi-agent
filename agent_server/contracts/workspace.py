"""Workspace contract types."""
from __future__ import annotations

from dataclasses import dataclass


# scope: process-internal — content-hash value object; carriers hold tenant_id
@dataclass(frozen=True)
class ContentHash:
    """SHA-256 content address for an object."""

    algorithm: str
    hex_digest: str

    @property
    def short(self) -> str:
        return self.hex_digest[:16]


@dataclass(frozen=True)
class BlobRef:
    """Reference to a content-addressed blob."""

    tenant_id: str
    content_hash: ContentHash
    size_bytes: int = 0
    media_type: str = "application/octet-stream"


@dataclass(frozen=True)
class WorkspaceObject:
    """A file-tree object in a tenant workspace."""

    tenant_id: str
    path: str
    blob_ref: BlobRef
    version: int = 1
    created_at: str = ""
