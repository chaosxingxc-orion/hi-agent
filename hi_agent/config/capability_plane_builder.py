"""CapabilityPlaneBuilder -- extracted from SystemBuilder (HI-W8-002).

Builds capability registry, artifact registry, MCP registry/transport, and harness.
Accepts llm_gateway as constructor param to break circular dependency.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.harness.evidence_store import EvidenceStore, SqliteEvidenceStore
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine

logger = logging.getLogger(__name__)


class CapabilityPlaneBuilder:
    def __init__(self, config: TraceConfig, llm_gateway: Any = None) -> None:
        self._config = config
        self._llm_gateway = llm_gateway
        self._lock = threading.RLock()
        self._capability_registry = None
        self._artifact_registry = None
        self._mcp_registry = None
        self._mcp_transport = None
        self._evidence_store = None

    def build_capability_registry(self) -> Any:
        """Build or return the shared CapabilityRegistry singleton.

        Business agents can register capabilities into this registry before
        calling :meth:`build_executor`.  The same registry instance is used
        by :meth:`_validate_required_capabilities` and :meth:`build_invoker`.
        """
        with self._lock:
            if not hasattr(self, "_capability_registry") or self._capability_registry is None:
                try:
                    from hi_agent.capability.defaults import (
                        register_default_capabilities,
                    )
                    from hi_agent.capability.registry import CapabilityRegistry
                    from hi_agent.capability.tools import register_builtin_tools

                    registry = CapabilityRegistry()
                    gateway = self._llm_gateway
                    try:
                        register_default_capabilities(registry, llm_gateway=gateway)
                    except Exception as exc:
                        logger.warning(
                            "build_capability_registry: register_default_capabilities failed (%s); "
                            "registry will have no pre-registered capabilities.",
                            exc,
                        )
                    register_builtin_tools(registry)
                    self._capability_registry = registry
                    logger.info(
                        "build_capability_registry: CapabilityRegistry created "
                        "with %d capabilities.",
                        len(registry.list_names()),
                    )
                except Exception as exc:
                    logger.warning("build_capability_registry: failed: %s", exc)
                    self._capability_registry = None
        return self._capability_registry

    def build_artifact_registry(self) -> Any:
        """Build or return the shared ArtifactRegistry singleton."""
        if not hasattr(self, "_artifact_registry") or self._artifact_registry is None:
            try:
                from hi_agent.artifacts.registry import ArtifactRegistry

                self._artifact_registry = ArtifactRegistry()
                logger.info("build_artifact_registry: ArtifactRegistry created.")
            except Exception as exc:
                from hi_agent.config.posture import Posture

                if Posture.from_env().is_strict:
                    raise
                logger.warning("build_artifact_registry: failed: %s", exc)
                self._artifact_registry = None
        return self._artifact_registry

    def build_mcp_registry(self) -> Any:
        """Build or return the shared MCPRegistry singleton."""
        with self._lock:
            if self._mcp_registry is None:
                try:
                    from hi_agent.mcp.registry import MCPRegistry

                    self._mcp_registry = MCPRegistry()
                    logger.info("build_mcp_registry: MCPRegistry created.")
                except Exception as exc:
                    logger.warning("build_mcp_registry: failed: %s", exc)
                    self._mcp_registry = None
        return self._mcp_registry

    def build_mcp_transport(self) -> Any:
        """Build or return the shared MultiStdioTransport singleton.

        Returns a ``MultiStdioTransport`` when MCP servers are registered with
        ``transport="stdio"``, otherwise returns ``None``.  The transport is
        passed to ``MCPBinding`` so that registered tools become invokable.
        """
        with self._lock:
            if self._mcp_transport is not None:
                return self._mcp_transport
            registry = self.build_mcp_registry()
            if registry is None:
                return None
            stdio_servers = [s for s in registry.list_servers() if s.get("transport") == "stdio"]
            if not stdio_servers:
                logger.debug(
                    "build_mcp_transport: no stdio MCP servers registered; transport not created."
                )
                return None
            try:
                from hi_agent.mcp.transport import MultiStdioTransport

                self._mcp_transport = MultiStdioTransport(mcp_registry=registry)
                logger.info(
                    "build_mcp_transport: MultiStdioTransport created for %d stdio server(s).",
                    len(stdio_servers),
                )
            except Exception as exc:
                logger.warning("build_mcp_transport: failed: %s", exc)
                self._mcp_transport = None
        return self._mcp_transport

    def build_harness(self, capability_invoker: Any | None = None) -> HarnessExecutor:
        """Build HarnessExecutor with config-driven governance.

        Args:
            capability_invoker: Optional pre-built CapabilityInvoker. When None,
                a real invoker is created so that
                ``HarnessExecutor._dispatch()`` never raises ``RuntimeError``.
        """
        governance = GovernanceEngine()
        if self._config.evidence_store_backend == "sqlite":
            with self._lock:
                if self._evidence_store is None:
                    self._evidence_store = SqliteEvidenceStore(
                        db_path=self._config.evidence_store_path
                    )
            evidence_store: EvidenceStore | SqliteEvidenceStore = self._evidence_store
        else:
            logger.warning(
                "build_harness: evidence_store_backend=%r -- using in-memory store. "
                "Evidence will not persist across restarts. "
                "Set evidence_store_backend='sqlite' for production.",
                self._config.evidence_store_backend,
            )
            evidence_store = EvidenceStore()
        if capability_invoker is None:
            from hi_agent.capability.circuit_breaker import CircuitBreaker
            from hi_agent.capability.invoker import CapabilityInvoker

            registry = self.build_capability_registry()
            if registry is None:
                from hi_agent.capability.registry import CapabilityRegistry

                registry = CapabilityRegistry()
                logger.warning("build_invoker: registry is None, using empty fallback registry.")
            breaker = CircuitBreaker()
            capability_invoker = CapabilityInvoker(
                registry=registry, breaker=breaker, allow_unguarded=True
            )
            logger.info(
                "build_invoker: using shared registry with %d capabilities.",
                len(registry.list_names()),
            )
        return HarnessExecutor(
            governance=governance,
            evidence_store=evidence_store,
            capability_invoker=capability_invoker,
            artifact_registry=self.build_artifact_registry(),
        )
