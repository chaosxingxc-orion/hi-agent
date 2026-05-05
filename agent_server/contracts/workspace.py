"""Workspace contract types."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_server.contracts.errors import SpineCompletenessError, _strict_posture

_LOGGER = logging.getLogger("agent_server.contracts.workspace")


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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"BlobRef constructed without required spine fields under "
                f"posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "blob_ref_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )


@dataclass(frozen=True)
class WorkspaceObject:
    """A file-tree object in a tenant workspace."""

    tenant_id: str
    path: str
    blob_ref: BlobRef
    version: int = 1
    created_at: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness."""
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not missing:
            return
        if _strict_posture():
            posture = "research/prod"
            raise SpineCompletenessError(
                f"WorkspaceObject constructed without required spine fields "
                f"under posture={posture}: missing={missing}. Populate at the "
                "construction site (Rule 12)."
            )
        _LOGGER.warning(
            "workspace_object_spine_incomplete: missing=%s posture=dev; "
            "would fail-closed under research/prod (W35-T1)",
            missing,
        )
