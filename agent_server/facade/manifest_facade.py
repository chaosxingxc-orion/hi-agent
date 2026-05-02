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

import logging
from collections.abc import Callable
from typing import Any

from agent_server import AGENT_SERVER_API_VERSION

_logger = logging.getLogger(__name__)

CapabilityMatrixFn = Callable[[], list[dict[str, Any]]]

# Hardcoded capability matrix used when Track D is not yet bound.
# Each entry: name, postures map ({dev, research, prod} -> bool), maturity
# (L0..L4 per Rule 13), description.
#
# W31-N (N.9): the previously L2-shaped entries for `memory` and
# `knowledge_graph` overstated maturity — both are L1 stubs at v1 (the
# routes return 200 but persist via a tenant-scoped log only). The
# matrix now reports the correct level alongside the dev/research/prod
# posture availability so downstream tools can plan accordingly.
_HARDCODED_MATRIX: list[dict[str, Any]] = [
    {
        "name": "runs",
        "description": "POST/GET/cancel/signal /v1/runs",
        "maturity": "L2",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "events",
        "description": "Server-Sent Events stream for a run",
        "maturity": "L2",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "artifacts",
        "description": "List + retrieve artifacts produced by a run",
        "maturity": "L2",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "manifest",
        "description": "Per-posture capability availability matrix",
        "maturity": "L2",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "memory",
        "description": "Tenant-scoped memory write (L1 stub; reads not yet exposed)",
        "maturity": "L1",
        "postures": {"dev": True, "research": True, "prod": False},
    },
    {
        "name": "skills",
        "description": "Skill registration (L1 stub; get/list/pin on v1.1 backlog)",
        "maturity": "L1",
        "postures": {"dev": True, "research": True, "prod": False},
    },
    {
        "name": "mcp_tools",
        "description": "MCP tools list/invoke (L1 stub; no tools registered)",
        "maturity": "L1",
        "postures": {"dev": True, "research": False, "prod": False},
    },
    {
        "name": "gates",
        "description": "POST /v1/gates/{gate_id}/decide",
        "maturity": "L2",
        "postures": {"dev": True, "research": True, "prod": True},
    },
    {
        "name": "knowledge_graph",
        "description": "L3 KG nodes + relationships (L1 forward; not yet wired)",
        "maturity": "L1",
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
            except Exception as exc:
                _logger.warning(
                    "manifest_facade: capability_matrix_callable failed, "
                    "falling back to hardcoded matrix: %s",
                    exc,
                )
        return {
            "api_version": AGENT_SERVER_API_VERSION,
            "capabilities": [dict(cap) for cap in _HARDCODED_MATRIX],
            "posture_matrix_provenance": "hardcoded",
        }


__all__ = ["ManifestFacade"]
