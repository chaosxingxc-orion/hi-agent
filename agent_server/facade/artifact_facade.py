"""Artifact facade — list + get with HD-4 closure (W24 Track I-B).

Under research/prod posture the facade refuses to surface artifacts whose
stored ``tenant_id`` is empty (HD-4 closure: 404, not "owned by everyone").
Under research/prod the facade also performs a content-hash recheck and
raises :class:`ArtifactIntegrityError` on mismatch — the route maps that
to HTTP 409.

Per R-AS-8 facade modules must stay <=200 LOC.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from hi_agent.config.posture import Posture

from agent_server.contracts.errors import ContractError, NotFoundError
from agent_server.contracts.tenancy import TenantContext

ListArtifactsFn = Callable[..., list[dict[str, Any]]]
GetArtifactFn = Callable[..., dict[str, Any]]


class ArtifactIntegrityError(ContractError):
    """Stored content does not match the recorded content_hash."""

    http_status = 409


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtifactFacade:
    """Adapter for /v1/runs/{id}/artifacts and /v1/artifacts/{id}."""

    def __init__(
        self,
        *,
        list_artifacts: ListArtifactsFn,
        get_artifact: GetArtifactFn,
    ) -> None:
        self._list_artifacts = list_artifacts
        self._get_artifact = get_artifact

    def list_for_run(
        self, ctx: TenantContext, run_id: str
    ) -> list[dict[str, Any]]:
        records = self._list_artifacts(
            tenant_id=ctx.tenant_id, run_id=run_id
        )
        out: list[dict[str, Any]] = []
        strict = Posture.from_env().is_strict
        for rec in records:
            owner = (rec.get("tenant_id") or "").strip()
            if strict and not owner:
                # HD-4 closure: do not surface orphan records under strict.
                continue
            out.append(_to_metadata_dict(rec))
        return out

    def get(
        self, ctx: TenantContext, artifact_id: str
    ) -> dict[str, Any]:
        record = self._get_artifact(
            tenant_id=ctx.tenant_id, artifact_id=artifact_id
        )
        owner = (record.get("tenant_id") or "").strip()
        if Posture.from_env().is_strict:
            if not owner:
                # HD-4: orphan records → 404 under strict posture.
                raise NotFoundError(
                    "artifact not found",
                    tenant_id=ctx.tenant_id,
                    detail=artifact_id,
                )
            self._verify_integrity(record, ctx.tenant_id)
        return _to_metadata_dict(record)

    def _verify_integrity(
        self, record: dict[str, Any], tenant_id: str
    ) -> None:
        recorded = record.get("content_hash") or ""
        content = record.get("content")
        if recorded and isinstance(content, (bytes, bytearray)):
            actual = _sha256_hex(bytes(content))
            if actual != recorded:
                raise ArtifactIntegrityError(
                    "artifact content hash mismatch",
                    tenant_id=tenant_id,
                    detail=record.get("artifact_id", ""),
                )


def _to_metadata_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Strip the raw bytes from a stored record before returning to clients."""
    out = {k: v for k, v in record.items() if k != "content"}
    return out


__all__ = ["ArtifactFacade", "ArtifactIntegrityError"]
