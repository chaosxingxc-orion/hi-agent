"""Manifest facade — capability matrix exposure (W24 Track I-C).

If Track D (per-capability matrix from CapabilityRegistry) has not landed,
this facade returns a hardcoded matrix and tags the response body with
``posture_matrix_provenance: "hardcoded"``. Once Track D lands, callers
will rebind via the optional ``capability_matrix_callable`` constructor
argument and the provenance tag flips to ``"capability_registry"``.

Per R-AS-1 this module imports only from agent_server.contracts and
stdlib — no ``hi_agent.*`` references inside ``agent_server/api/``.
Per R-AS-8 facade modules must stay <=200 LOC.
"""
from __future__ import annotations

from typing import Any, Callable

from agent_server import AGENT_SERVER_API_VERSION

CapabilityMatrixFn = Callable[[], list[dict[str, Any]]]

# Hardcoded capability matrix used when Track D is not yet bound.
# Each entry: name, postures map ({dev, research, prod} -> bool), notes.
_HARDCODED_MATRIX: list[dict[str, Any]] = [
    {
        "name": "runs",
        "description": "POST/GET/cancel/signal /v1/runs",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "events",
        "description": "Server-Sent Events stream for a run",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "artifacts",
        "description": "List + retrieve artifacts produced by a run",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "manifest",
        "description": "Per-posture capability availability matrix",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "memory",
        "description": "Tenant-scoped memory write/read (forward)",
        "postures": {"dev": True, "research": True, "prod": False},
    },
    {
        "name": "knowledge_graph",
        "description": "L3 KG nodes + relationships (forward)",
        "postures": {"dev": True, "research": True, "prod": False},
    },
]


class ManifestFacade:
    """Adapter for the /v1/manifest endpoint."""

    def __init__(
        self,
        *,
        capability_matrix_callable: CapabilityMatrixFn | None = None,
    ) -> None:
        self._matrix_callable = capability_matrix_callable

    def manifest(self) -> dict[str, Any]:
        if self._matrix_callable is not None:
            try:
                caps = list(self._matrix_callable())
                return {
                    "api_version": AGENT_SERVER_API_VERSION,
                    "capabilities": caps,
                    "posture_matrix_provenance": "capability_registry",
                }
            except Exception:  # noqa: BLE001 - downgrade to hardcoded
                pass
        return {
            "api_version": AGENT_SERVER_API_VERSION,
            "capabilities": [dict(cap) for cap in _HARDCODED_MATRIX],
            "posture_matrix_provenance": "hardcoded",
        }


__all__ = ["ManifestFacade"]
