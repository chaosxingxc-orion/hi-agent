"""Manifest response contract (W34 Track C, B-W34-5).

The /v1/manifest endpoint exposes the platform-wide execution posture so
downstream callers can refuse to start under a misaligned configuration.
The Research Intelligence App (RIA) is the canonical consumer: per
acceptance ID **R-RIA-6**, RIA refuses to start under prod against a
dev-posture platform, using the ``posture`` field on this response as
the authoritative signal.

Per Rule 12 (Contract Spine Completeness) the manifest is tenant-agnostic
by design: it describes platform-level capability availability and the
resolved execution posture, neither of which is tenant-scoped. The
``ManifestResponse`` dataclass therefore omits ``tenant_id``; the
``# scope: process-internal`` marker on the class declaration documents
this decision and lets ``check_contract_spine_completeness.py`` exempt
it from the gate.

Per R-AS-7 (contracts purity, enforced by ``check_contracts_purity.py``)
this module imports only stdlib + ``typing`` + ``dataclasses``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Posture values surfaced on the manifest. Mirrors
# ``hi_agent.config.posture.Posture`` member values; kept as a Literal
# here so this contracts module stays free of platform imports per
# R-AS-7.
PostureLiteral = Literal["dev", "research", "prod"]


# scope: process-internal — manifest is platform-wide; not tenant-scoped (R-RIA-6).
@dataclass(frozen=True)
class ManifestResponse:
    """Response body for ``GET /v1/manifest``.

    Fields
    ------
    api_version:
        Mirrors :data:`agent_server.AGENT_SERVER_API_VERSION`.
    posture:
        Resolved platform execution posture. Consumed by RIA per
        acceptance ID **R-RIA-6** to refuse start-up under prod against
        a dev-posture platform.
    capabilities:
        Per-capability availability matrix; preserves the existing
        shape (one entry per capability with ``name``, ``description``,
        ``maturity``, ``postures`` fields).
    posture_matrix_provenance:
        ``"capability_registry"`` when the matrix was derived from the
        live ``CapabilityRegistry``; ``"hardcoded"`` when the facade
        fell back to its bundled list. Preserves the v1 wire field.
    """

    api_version: str
    posture: PostureLiteral
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    posture_matrix_provenance: str = "hardcoded"


__all__ = ["ManifestResponse", "PostureLiteral"]
