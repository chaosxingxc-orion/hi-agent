"""Factory that creates all TRACE subsystems from a single TraceConfig."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.harness.evidence_store import EvidenceStore, SqliteEvidenceStore
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine
from hi_agent.llm.protocol import LLMGateway
from hi_agent.memory import MemoryCompressor
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.observability.collector import MetricsCollector
from hi_agent.orchestrator.task_orchestrator import TaskOrchestrator
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import SkillRegistry
from hi_agent.state import RunStateStore


class MissingCapabilityError(RuntimeError):
    """Raised when a profile's required capabilities are not registered."""


class SystemBuilder:
    """Factory that creates all TRACE subsystems from a single TraceConfig.

    This is the main assembly point -- creates properly configured
    instances of all subsystems and wires them together.
    """

    def __init__(
        self,
        config: TraceConfig | None = None,
        config_stack: Any | None = None,
        *,
        profile_registry: Any | None = None,
        capability_registry: Any | None = None,
        artifact_registry: Any | None = None,
    ) -> None:
        """Initialize SystemBuilder.

        Args:
            config: Optional TraceConfig. Defaults to a new TraceConfig().
            config_stack: Optional config stack (used by server wiring).
            profile_registry: Optional pre-built ProfileRegistry. When provided,
                build_profile_registry() returns it directly without creating a new one.
            capability_registry: Optional pre-built CapabilityRegistry. When provided,
                build_capability_registry() returns it directly without creating a new one.
            artifact_registry: Optional pre-built ArtifactRegistry. When provided,
                build_artifact_registry() returns it directly without creating a new one.
        """
        import threading as _threading

        self._config = config if config is not None else TraceConfig()
        self._stack = config_stack
        # Protects lazy singleton cache against concurrent build_executor() calls.
        # RLock (re-entrant) is required because several build_* methods acquire
        # this lock and then call other build_* methods that also acquire it
        # (e.g. build_capability_registry -> build_llm_gateway).
        self._singleton_lock = _threading.RLock()
        # Cache built singletons so repeated calls return the same instance.
        self._kernel: RuntimeAdapter | None = None
        self._llm_gateway: LLMGateway | None = None
        self._metrics_collector: MetricsCollector | None = None
        self._tier_router: Any | None = None  # cached alongside _llm_gateway
        self._run_context_manager: Any | None = None
        self._middleware_orchestrator: Any | None = None
        self._llm_budget_tracker: Any | None = None
        # Subsystem singletons — cached so readiness() and manifest reflect the
        # same instances used by actual run execution.
        self._skill_loader: Any | None = None
        self._skill_builder: Any | None = None  # lazy SkillBuilder singleton
        self._memory_builder: Any | None = None  # lazy MemoryBuilder singleton
        self._server_builder: Any | None = None  # lazy ServerBuilder singleton
        self._capability_plane_builder: Any | None = None  # lazy CapabilityPlaneBuilder singleton
        self._cognition_builder: Any | None = None  # lazy CognitionBuilder singleton
        self._runtime_builder: Any | None = None  # lazy RuntimeBuilder singleton
        self._mcp_registry: Any | None = None
        self._mcp_transport: Any | None = None
        self._plugin_loader: Any | None = None
        self._evidence_store: Any | None = None
        # Pre-inject registries if provided (allows derived builders to inherit state).
        # The build_*_registry() methods all use hasattr/is-None checks before creating
        # new instances, so pre-assigned values will be respected automatically.
        if profile_registry is not None:
            self._profile_registry = profile_registry
        if capability_registry is not None:
            self._capability_registry = capability_registry
        if artifact_registry is not None:
            self._artifact_registry = artifact_registry

        # Redirect deprecated TraceConfig fields to their successors before any
        # subsystem is built, so callers that set legacy fields get expected behavior.
        self._redirect_deprecated_config()
        # Warn about deprecated fields that have no successor (dead fields).
        self._config.validate_no_deprecated()

    def _redirect_deprecated_config(self) -> None:
        """Forward deprecated TraceConfig fields to their active successors.

        This preserves backward compatibility for callers that still set the old
        field names.  Only redirects when the successor field still holds its
        default value — explicit successor values always win.
        """
        cfg = self._config
        # default_model → openai_default_model (when successor is still the package default)
        if cfg.default_model != "gpt-4o" and cfg.openai_default_model == "gpt-4o":
            cfg.openai_default_model = cfg.default_model
        # llm_max_retries → llm_failover_max_retries
        if cfg.llm_max_retries != 2 and cfg.llm_failover_max_retries == 3:
            cfg.llm_failover_max_retries = cfg.llm_max_retries
        # harness_default_timeout → harness_action_default_timeout
        if cfg.harness_default_timeout != 60 and cfg.harness_action_default_timeout == 60:
            cfg.harness_action_default_timeout = cfg.harness_default_timeout
        # max_actions_per_run → task_budget_max_actions
        if cfg.max_actions_per_run != 100 and cfg.task_budget_max_actions == 50:
            cfg.task_budget_max_actions = cfg.max_actions_per_run
        # max_total_branches → cts_max_total_branches
        if cfg.max_total_branches != 20 and cfg.cts_max_total_branches == 20:
            cfg.cts_max_total_branches = cfg.max_total_branches
        # max_branches_per_stage → cts_max_active_branches_per_stage
        if cfg.max_branches_per_stage != 5 and cfg.cts_max_active_branches_per_stage == 3:
            cfg.cts_max_active_branches_per_stage = cfg.max_branches_per_stage

    # ------------------------------------------------------------------
    # Individual builders
    # ------------------------------------------------------------------

    def _build_run_context_manager(self) -> Any:
        """Build or return the shared RunContextManager singleton."""
        return self._get_runtime_builder().build_run_context_manager()

    def _build_middleware_orchestrator(self) -> Any:
        """Build or return the shared MiddlewareOrchestrator singleton."""
        return self._get_runtime_builder().build_middleware_orchestrator()

    def _inject_middleware_dependencies(self, orchestrator: Any, *, profile_id: str) -> None:
        """Post-inject subsystem dependencies into orchestrator's middleware instances.

        Rule 13 (DF-27): ``profile_id`` is required so knowledge / retrieval
        builders can scope their stores correctly.
        """
        self._get_runtime_builder().inject_middleware_dependencies(
            orchestrator, profile_id=profile_id
        )

    def _build_llm_budget_tracker(self) -> Any:
        """Build LLMBudgetTracker — delegated to CognitionBuilder."""
        return self._get_cognition_builder()._build_llm_budget_tracker()

    def _build_restart_policy_engine(self) -> Any:
        """Build RestartPolicyEngine — delegated to RuntimeBuilder."""
        return self._get_runtime_builder().build_restart_policy_engine()

    def _build_reflection_orchestrator(self) -> Any:
        """Build ReflectionOrchestrator — delegated to CognitionBuilder."""
        return self._get_cognition_builder().build_reflection_orchestrator()

    def build_metrics_collector(self) -> MetricsCollector:
        """Build or return the shared MetricsCollector singleton."""
        return self._get_runtime_builder().build_metrics_collector()

    def build_kernel(self) -> RuntimeAdapter:
        """Build kernel adapter (HTTP or in-process LocalFSM)."""
        return self._get_runtime_builder().build_kernel()

    def build_llm_gateway(self) -> LLMGateway | None:
        """Build LLM gateway — delegated to CognitionBuilder."""
        gw = self._get_cognition_builder().build_llm_gateway()
        # Keep backward-compat cached refs on SystemBuilder so code that reads
        # self._llm_gateway / self._tier_router still works.
        if gw is not None:
            self._llm_gateway = gw
            self._tier_router = self._get_cognition_builder()._tier_router
        return gw

    def build_evolve_engine(self) -> EvolveEngine:
        """Build EvolveEngine — delegated to CognitionBuilder."""
        return self._get_cognition_builder().build_evolve_engine()

    def build_invoker(self) -> Any:
        """Build a CapabilityInvoker using the SHARED capability registry singleton.

        IMPORTANT: Uses self.build_capability_registry() — the same registry instance
        that _validate_required_capabilities() checks. Any capability registered via
        builder.build_capability_registry().register(...) is immediately available
        to the harness executor.
        """
        from hi_agent.capability.circuit_breaker import CircuitBreaker
        from hi_agent.capability.invoker import CapabilityInvoker

        registry = (
            self.build_capability_registry()
        )  # shared singleton — NOT a fresh CapabilityRegistry()
        if registry is None:
            # Registry construction failed — create a minimal empty registry so
            # the invoker is never constructed with None, preventing AttributeError
            # downstream. The invoker will be usable but have no capabilities.
            from hi_agent.capability.registry import CapabilityRegistry

            registry = CapabilityRegistry()
            logger.warning("build_invoker: registry is None, using empty fallback registry.")
        breaker = CircuitBreaker()
        invoker = CapabilityInvoker(registry=registry, breaker=breaker, allow_unguarded=True)
        logger.info(
            "build_invoker: using shared registry with %d capabilities.",
            len(registry.list_names()),
        )
        return invoker

    def build_capability_registry(self) -> Any:
        """Build or return the shared CapabilityRegistry singleton.

        Business agents can register capabilities into this registry before
        calling :meth:`build_executor`.  The same registry instance is used
        by :meth:`_validate_required_capabilities` and :meth:`build_invoker`.
        """
        with self._singleton_lock:
            if not hasattr(self, "_capability_registry") or self._capability_registry is None:
                try:
                    from hi_agent.capability.defaults import (
                        register_default_capabilities,
                    )
                    from hi_agent.capability.registry import CapabilityRegistry
                    from hi_agent.capability.tools import register_builtin_tools

                    registry = CapabilityRegistry()
                    gateway = self.build_llm_gateway()
                    try:
                        register_default_capabilities(registry, llm_gateway=gateway)
                    except Exception as exc:
                        logger.warning(
                            "build_capability_registry: register_default_capabilities failed (%s); "
                            "registry will have no pre-registered capabilities.",
                            exc,
                        )
                    import os as _os_rbt

                    from hi_agent.server.runtime_mode_resolver import (
                        resolve_runtime_mode as _rrm_rbt,
                    )

                    _env_rbt = _os_rbt.environ.get("HI_AGENT_ENV", "dev").lower()
                    try:
                        _readiness_rbt = self.readiness()
                    except Exception:
                        _readiness_rbt = {}
                    _profile_rbt = _rrm_rbt(_env_rbt, _readiness_rbt)
                    register_builtin_tools(registry, profile=_profile_rbt)
                    # Load config-driven custom tools (config/tools.json).
                    try:
                        import os as _os_tc

                        from hi_agent.config.tools_config_loader import load_tools_from_config

                        _tools_path = _os_tc.path.join(
                            _os_tc.path.dirname(__file__), "..", "..", "config", "tools.json"
                        )
                        load_tools_from_config(registry, config_path=_tools_path)
                    except Exception as _tc_exc:
                        logger.warning(
                            "build_capability_registry: tools_config_loader failed (%s); "
                            "custom tools not loaded.",
                            _tc_exc,
                        )
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
        """Build or return the shared ArtifactRegistry singleton.

        When episodic_storage_dir is configured, returns a durable ArtifactLedger
        backed by a JSONL file so artifacts survive process restarts.
        Falls back to in-memory ArtifactRegistry when no storage path is available.
        """
        if not hasattr(self, "_artifact_registry") or self._artifact_registry is None:
            try:
                episodic_dir = getattr(self._config, "episodic_storage_dir", None)
                if episodic_dir:
                    from pathlib import Path

                    from hi_agent.artifacts.ledger import ArtifactLedger

                    project_id = getattr(self._config, "project_id", "")
                    base = str(Path(episodic_dir).parent)
                    ledger_dir = Path(base) / "artifacts"
                    if project_id:
                        ledger_dir = ledger_dir / project_id
                    self._artifact_registry = ArtifactLedger(ledger_dir / "ledger.jsonl")
                    logger.info(
                        "build_artifact_registry: ArtifactLedger created at %s.",
                        ledger_dir / "ledger.jsonl",
                    )
                else:
                    from hi_agent.artifacts.registry import ArtifactRegistry

                    self._artifact_registry = ArtifactRegistry()
                    logger.info("build_artifact_registry: ArtifactRegistry created (in-memory).")
            except Exception as exc:
                logger.warning("build_artifact_registry: failed: %s", exc)
                self._artifact_registry = None
        return self._artifact_registry

    def build_mcp_registry(self) -> Any:
        """Build or return the shared MCPRegistry singleton."""
        with self._singleton_lock:
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
        with self._singleton_lock:
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
                a real invoker is created via :meth:`build_invoker` so that
                ``HarnessExecutor._dispatch()`` never raises ``RuntimeError``.
        """
        governance = GovernanceEngine()
        if self._config.evidence_store_backend == "sqlite":
            with self._singleton_lock:
                if self._evidence_store is None:
                    self._evidence_store = SqliteEvidenceStore(
                        db_path=self._config.evidence_store_path
                    )
            evidence_store: EvidenceStore | SqliteEvidenceStore = self._evidence_store
        else:
            logger.warning(
                "build_harness: evidence_store_backend=%r — using in-memory store. "
                "Evidence will not persist across restarts. "
                "Set evidence_store_backend='sqlite' for production.",
                self._config.evidence_store_backend,
            )
            evidence_store = EvidenceStore()
        if capability_invoker is None:
            capability_invoker = self.build_invoker()
        return HarnessExecutor(
            governance=governance,
            evidence_store=evidence_store,
            capability_invoker=capability_invoker,
            artifact_registry=self.build_artifact_registry(),
        )

    def _get_skill_builder(self):
        if self._skill_builder is None:
            from hi_agent.config.skill_builder import SkillBuilder

            self._skill_builder = SkillBuilder(self._config)
        return self._skill_builder

    def _get_memory_builder(self):
        if self._memory_builder is None:
            from hi_agent.config.memory_builder import MemoryBuilder

            self._memory_builder = MemoryBuilder(self._config)
        return self._memory_builder

    def _get_server_builder(self):
        if self._server_builder is None:
            from hi_agent.config.server_builder import ServerBuilder

            self._server_builder = ServerBuilder(self._config)
        return self._server_builder

    def _get_knowledge_builder(self):
        if not hasattr(self, "_knowledge_builder_inst") or self._knowledge_builder_inst is None:
            from hi_agent.config.knowledge_builder import KnowledgeBuilder

            # Adapt the keyword-only signature of build_long_term_graph into
            # the factory's positional protocol: factory(profile_id) -> graph.
            self._knowledge_builder_inst = KnowledgeBuilder(
                self._config,
                long_term_graph_factory=lambda pid: self.build_long_term_graph(
                    profile_id=pid, workspace_key=None
                ),
            )
        return self._knowledge_builder_inst

    def _get_capability_plane_builder(self):
        if self._capability_plane_builder is None:
            from hi_agent.config.capability_plane_builder import CapabilityPlaneBuilder

            self._capability_plane_builder = CapabilityPlaneBuilder(
                self._config,
                llm_gateway=self.build_llm_gateway(),
            )
        return self._capability_plane_builder

    def _get_cognition_builder(self):
        """Return shared CognitionBuilder singleton (LLM gateway, evolve engine)."""
        if self._cognition_builder is None:
            from hi_agent.config.cognition_builder import CognitionBuilder

            self._cognition_builder = CognitionBuilder(
                self._config,
                self._singleton_lock,
                skill_version_mgr_fn=self.build_skill_version_manager,
            )
        return self._cognition_builder

    def _get_runtime_builder(self):
        """Return shared RuntimeBuilder singleton (kernel, metrics, middleware, executor)."""
        if self._runtime_builder is None:
            from hi_agent.config.runtime_builder import RuntimeBuilder

            self._runtime_builder = RuntimeBuilder(
                self._config,
                self._singleton_lock,
                parent=self,
            )
        return self._runtime_builder

    def build_skill_registry(self) -> SkillRegistry:
        """Build SkillRegistry using configured storage directory."""
        return self._get_skill_builder().build_skill_registry()

    def build_skill_loader(self) -> Any:
        """Build or return the shared SkillLoader singleton."""
        loader = self._get_skill_builder().build_skill_loader()
        self._skill_loader = loader  # keep local ref for _wire_plugin_contributions
        return loader

    def build_plugin_loader(self) -> Any:
        """Build or return the shared PluginLoader singleton.

        Loads and activates plugins from the default plugin directories
        (.hi_agent/plugins, ~/.hi_agent/plugins). Returns the cached singleton
        on subsequent calls so the same instance is shared across server
        endpoints and executor builds.
        """
        if self._plugin_loader is None:
            from hi_agent.plugin.loader import PluginLoader

            self._plugin_loader = PluginLoader()
            self._plugin_loader.load_all()
            activated = self._plugin_loader.activate_all()
            if activated:
                logger.info("build_plugin_loader: activated %d plugin(s).", activated)
        return self._plugin_loader

    def _wire_plugin_contributions(self) -> None:
        """Wire plugin manifest declarations (skill_dirs, mcp_servers) into live subsystems.

        Called once after all subsystems are built so plugins can extend the
        platform without requiring restart. Capability declarations are logged
        but not auto-registered (require entry_point execution).
        """
        if self._plugin_loader is None:
            return

        # Load top-level mcp_servers.json BEFORE plugin contributions.
        if not getattr(self, "_mcp_config_loaded", False):
            self._mcp_config_loaded = True
            if self._mcp_registry is not None:
                try:
                    import os as _os_mcp

                    from hi_agent.config.mcp_config_loader import load_mcp_servers_from_config

                    _mcp_cfg_path = _os_mcp.path.join(
                        _os_mcp.path.dirname(__file__), "..", "..", "config", "mcp_servers.json"
                    )
                    load_mcp_servers_from_config(
                        self._mcp_registry, config_path=_mcp_cfg_path
                    )
                except Exception as _mcp_cfg_exc:
                    logger.warning(
                        "_wire_plugin_contributions: mcp_config_loader failed (%s); "
                        "config-driven MCP servers not loaded.",
                        _mcp_cfg_exc,
                    )

        for manifest in self._plugin_loader._loaded.values():
            if manifest.status != "active":
                continue
            plugin_dir = manifest.plugin_dir or ""

            # Wire skill_dirs into the SkillLoader search paths.
            if manifest.skill_dirs and self._skill_loader is not None:
                import os

                for skill_dir in manifest.skill_dirs:
                    resolved = os.path.join(plugin_dir, skill_dir) if plugin_dir else skill_dir
                    search_dirs = getattr(self._skill_loader, "_search_dirs", [])
                    if resolved not in search_dirs:
                        try:
                            search_dirs.append(resolved)
                            self._skill_loader.load_dir(resolved, source=f"plugin:{manifest.name}")
                            logger.info(
                                "_wire_plugin_contributions: loaded skills from %r (plugin %r).",
                                resolved,
                                manifest.name,
                            )
                        except Exception as exc:
                            logger.warning(
                                "_wire_plugin_contributions: could not load skill_dir %r: %s",
                                resolved,
                                exc,
                            )

            # Register mcp_servers into MCPRegistry.
            if manifest.mcp_servers and self._mcp_registry is not None:
                for srv_cfg in manifest.mcp_servers:
                    srv_name = srv_cfg.get("name", manifest.name)
                    srv_id = srv_cfg.get("id", f"{manifest.name}:{srv_name}")
                    try:
                        self._mcp_registry.register(
                            server_id=srv_id,
                            name=srv_name,
                            transport=srv_cfg.get("transport", "stdio"),
                            endpoint=srv_cfg.get("endpoint", ""),
                            tools=srv_cfg.get("tools"),
                        )
                        logger.info(
                            "_wire_plugin_contributions: registered MCP server %r from plugin %r.",
                            srv_name,
                            manifest.name,
                        )
                    except Exception as exc:
                        logger.warning(
                            "_wire_plugin_contributions: failed to register MCP server %r: %s",
                            srv_name,
                            exc,
                        )

            # Log declared capabilities (actual handler registration requires entry_point).
            if manifest.capabilities:
                logger.info(
                    "_wire_plugin_contributions: plugin %r declares capabilities %s; "
                    "set entry_point to auto-register handlers.",
                    manifest.name,
                    manifest.capabilities,
                )

        # After all plugin MCP servers are registered, (re-)build the transport
        # and close the provider circuit by calling MCPBinding.bind_all().
        if self._mcp_registry is not None:
            stdio_count = sum(
                1 for s in self._mcp_registry.list_servers() if s.get("transport") == "stdio"
            )
            if stdio_count > 0 and self._mcp_transport is None:
                self.build_mcp_transport()
            # Probe every declared server before binding.  Only servers that
            # pass a real JSON-RPC initialize handshake are promoted to
            # "healthy"; unreachable servers stay "registered" and are tracked
            # as unavailable in MCPBinding.bind_all().
            if self._mcp_transport is not None:
                try:
                    from hi_agent.mcp.health import MCPHealth

                    _hc = MCPHealth(self._mcp_registry, transport=self._mcp_transport)
                    _hc.check_all()
                    logger.debug("_wire_plugin_contributions: MCP health probe completed.")
                except Exception as _hc_exc:
                    logger.warning(
                        "_wire_plugin_contributions: MCP health probe failed: %s", _hc_exc
                    )
            # Wire external MCP tools into CapabilityRegistry so they are
            # invokable as standard capabilities.  This closes the circuit:
            # register → health-check → bind → capability.
            if self._mcp_transport is not None:
                try:
                    from hi_agent.mcp.binding import MCPBinding

                    cap_registry = self.build_capability_registry()
                    mcp_reg = self.build_mcp_registry()
                    _binding = MCPBinding(
                        registry=cap_registry,
                        mcp_registry=mcp_reg,
                        transport=self._mcp_transport,
                    )
                    _bound = _binding.bind_all()
                    logger.info(
                        "_wire_plugin_contributions: MCPBinding.bind_all() "
                        "registered %d MCP tool(s).",
                        _bound,
                    )
                except Exception as _mcp_exc:
                    logger.warning(
                        "_wire_plugin_contributions: MCPBinding.bind_all() failed: %s", _mcp_exc
                    )

    def build_skill_observer(self) -> Any:
        """Build SkillObserver for execution telemetry."""
        return self._get_skill_builder().build_skill_observer()

    def build_skill_version_manager(self) -> Any:
        """Build SkillVersionManager for champion/challenger versioning."""
        return self._get_skill_builder().build_skill_version_manager()

    def build_skill_evolver(self) -> Any:
        """Build or return the shared SkillEvolver singleton."""
        return self._get_skill_builder().build_skill_evolver(llm_gateway=self.build_llm_gateway())

    def build_episodic_store(self) -> EpisodicMemoryStore:
        """Build EpisodicMemoryStore using configured storage directory."""
        return self._get_memory_builder().build_episodic_store()

    def build_failure_collector(self) -> FailureCollector:
        """Build a fresh FailureCollector."""
        return self._get_memory_builder().build_failure_collector()

    def build_watchdog(self) -> ProgressWatchdog:
        """Build ProgressWatchdog with config-driven thresholds."""
        return self._get_memory_builder().build_watchdog()

    # ------------------------------------------------------------------
    # Memory tier builders
    # ------------------------------------------------------------------

    def build_short_term_store(self, *, profile_id: str, workspace_key: Any) -> Any:
        """Build short-term memory store scoped to a profile or workspace.

        Rule 6 / Rule 13 (DF-12): both ``profile_id`` and ``workspace_key``
        are keyword-only and required (no silent unscoped fallback).
        """
        return self._get_memory_builder().build_short_term_store(
            profile_id=profile_id, workspace_key=workspace_key
        )

    def build_mid_term_store(self, *, profile_id: str, workspace_key: Any) -> Any:
        """Build mid-term memory store scoped to a profile or workspace.

        Rule 6 / Rule 13 (DF-12): both ``profile_id`` and ``workspace_key``
        are keyword-only and required (no silent unscoped fallback).
        """
        return self._get_memory_builder().build_mid_term_store(
            profile_id=profile_id, workspace_key=workspace_key
        )

    def build_long_term_graph(self, *, profile_id: str, workspace_key: Any) -> Any:
        """Build long-term memory graph scoped to a profile or workspace.

        Rule 6 / Rule 13 (DF-12): both ``profile_id`` and ``workspace_key``
        are keyword-only and required (no silent unscoped fallback).
        """
        return self._get_memory_builder().build_long_term_graph(
            profile_id=profile_id, workspace_key=workspace_key
        )

    def build_retrieval_engine(
        self,
        *,
        profile_id: str,
        short_term_store: Any = None,
        mid_term_store: Any = None,
        long_term_graph: Any = None,
    ) -> Any:
        """Build four-layer retrieval engine across all memory tiers.

        Rule 13 (DF-12): ``profile_id`` keyword-only and required.
        """
        return self._get_memory_builder().build_retrieval_engine(
            short_term_store=short_term_store,
            mid_term_store=mid_term_store,
            long_term_graph=long_term_graph,
            profile_id=profile_id,
            wiki=self.build_knowledge_wiki(),
        )

    def build_memory_lifecycle_manager(
        self,
        *,
        profile_id: str,
        short_term_store: Any = None,
        mid_term_store: Any = None,
        long_term_graph: Any = None,
    ) -> MemoryLifecycleManager:
        """Build MemoryLifecycleManager wiring all memory tiers.

        Rule 13 (DF-12): ``profile_id`` keyword-only and required.
        """
        return self._get_memory_builder().build_memory_lifecycle_manager(
            short_term_store=short_term_store,
            mid_term_store=mid_term_store,
            long_term_graph=long_term_graph,
            profile_id=profile_id,
            wiki=self.build_knowledge_wiki(),
        )

    # ------------------------------------------------------------------
    # Knowledge tier builders
    # ------------------------------------------------------------------

    def build_knowledge_wiki(self) -> Any:
        return self._get_knowledge_builder().build_knowledge_wiki()

    def build_user_knowledge_store(self) -> Any:
        return self._get_knowledge_builder().build_user_knowledge_store()

    def build_knowledge_manager(self, *, profile_id: str, long_term_graph: Any = None) -> Any:
        """Build KnowledgeManager scoped to ``profile_id``.

        Rule 13 (DF-12): ``profile_id`` keyword-only and required.
        """
        return self._get_knowledge_builder().build_knowledge_manager(
            profile_id=profile_id, long_term_graph=long_term_graph
        )

    # ------------------------------------------------------------------
    # Composite builders
    # ------------------------------------------------------------------

    def _build_compressor(self) -> MemoryCompressor:
        """Create MemoryCompressor, wiring LLM gateway if available.

        DF-34: pin the compression model to ``glm-5.1`` (volces coding-plan
        ``strong`` tier) so memory compression does not hit
        ``UnsupportedModel`` when the configured ``light`` tier points at a
        model the coding-plan endpoint does not serve.  Quality matters more
        than cost for memory compression (low-frequency operation).
        """
        return MemoryCompressor(
            gateway=self.build_llm_gateway(),
            compress_threshold=self._config.memory_compress_threshold,
            timeout_s=self._config.memory_compress_timeout_seconds,
            fallback_items=self._config.memory_compress_fallback_items,
            max_findings=self._config.memory_compress_max_findings,
            max_decisions=self._config.memory_compress_max_decisions,
            max_entities=self._config.memory_compress_max_entities,
            max_tokens=self._config.memory_compress_max_tokens,
            compression_model="glm-5.1",
        )

    def build_profile_registry(self) -> Any:
        """Build or return the platform ProfileRegistry singleton.

        Business agents register their ProfileSpec instances into this registry
        before submitting runs.  The SystemBuilder reads from it during
        executor construction when a ``profile_id`` is present on the contract.
        """
        if not hasattr(self, "_profile_registry") or self._profile_registry is None:
            try:
                from hi_agent.profiles.registry import ProfileRegistry

                self._profile_registry = ProfileRegistry()
                logger.info("build_profile_registry: ProfileRegistry created.")
            except Exception as exc:
                logger.warning("build_profile_registry: failed: %s", exc)
                self._profile_registry = None
        return self._profile_registry

    def register_profile(self, spec: Any) -> None:
        """Register a ProfileSpec with this builder's ProfileRegistry.

        Upper-layer packages should call this to register profiles without
        relying on builder internals::

            builder = SystemBuilder()
            builder.register_profile(build_rnd_profile_spec())
            executor = builder.build_executor(contract)
        """
        self.build_profile_registry().register(spec)

    def _validate_required_capabilities(self, resolved_profile: Any) -> None:
        """Raise MissingCapabilityError if required capabilities are not registered."""
        try:
            registry = self.build_capability_registry()
            registered = set(registry.list_names()) if hasattr(registry, "list_names") else set()
        except Exception:
            registered = set()

        required = set(resolved_profile.required_capabilities)
        missing = required - registered
        if missing:
            raise MissingCapabilityError(
                f"Profile '{resolved_profile.profile_id}' requires capabilities that are not "
                f"registered: {sorted(missing)}. "
                f"Register them via CapabilityRegistry before building the executor."
            )

    def _resolve_profile(self, profile_id: str | None) -> Any:
        """Resolve a profile_id to a ResolvedProfile, or None for TRACE defaults."""
        if not profile_id:
            return None
        try:
            from hi_agent.runtime.profile_runtime import ProfileRuntimeResolver

            registry = self.build_profile_registry()
            if registry is None:
                return None
            return ProfileRuntimeResolver(registry).resolve(profile_id)
        except Exception as exc:
            logger.warning("_resolve_profile: failed for %r: %s", profile_id, exc)
            return None

    def _build_route_engine(self, stage_actions: dict | None = None) -> HybridRouteEngine:
        """Create HybridRouteEngine with LLM gateway + SkillMatcher if available.

        Args:
            stage_actions: Optional stage→capability mapping from a profile.
                When provided, the internal RuleRouteEngine uses these actions
                instead of the TRACE sample defaults.
        """
        from hi_agent.route_engine.rule_engine import RuleRouteEngine

        registry = self.build_skill_registry()
        gateway = self.build_llm_gateway()
        matcher = SkillMatcher(registry=registry) if registry else None
        rule_engine = RuleRouteEngine(
            skill_matcher=matcher,
            stage_actions=stage_actions,  # None → TRACE ClassVar defaults
        )
        return HybridRouteEngine(
            rule_engine=rule_engine,
            gateway=gateway,
            skill_matcher=matcher,
            confidence_threshold=self._config.route_confidence_threshold,
        )

    def _build_skill_recorder(self) -> SkillUsageRecorder:
        """Create SkillUsageRecorder with the skill registry."""
        return SkillUsageRecorder(registry=self.build_skill_registry())

    def build_context_manager(
        self,
        session: Any = None,
        memory_retriever: Any = None,
        skill_loader: Any = None,
        compressor: Any = None,
    ) -> Any:
        """Build ContextManager with config-driven budget and threshold wiring."""
        from hi_agent.context.manager import ContextManager

        if compressor is None:
            compressor = self._build_compressor()
        if skill_loader is None and hasattr(self, "build_skill_loader"):
            skill_loader = self.build_skill_loader()
        return ContextManager.from_config(
            self._config,
            session=session,
            memory_retriever=memory_retriever,
            skill_loader=skill_loader,
            compressor=compressor,
        )

    def build_budget_guard(self, total_budget_tokens: int | None = None) -> Any:
        """Build BudgetGuard with config-driven total token budget."""
        from hi_agent.task_mgmt.budget_guard import BudgetGuard

        budget = total_budget_tokens or self._config.llm_budget_max_tokens
        return BudgetGuard.from_config(self._config, total_budget_tokens=budget)

    def _wire_cost_optimizer(self, tier_router: Any, run_history: list | None = None) -> None:
        """Delegated to CognitionBuilder — kept for backward compatibility."""
        self._get_cognition_builder()._wire_cost_optimizer(tier_router, run_history)

    def _build_delegation_manager(self) -> Any:
        """Build DelegationManager with config-driven concurrency and polling parameters.

        Wires the shared kernel adapter and async LLM gateway (for result
        summarization) so that child runs can be spawned and their outputs
        compressed before injection into the parent context window.
        """
        try:
            from hi_agent.task_mgmt.delegation import DelegationConfig, DelegationManager

            config = DelegationConfig(
                max_concurrent=getattr(self._config, "delegation_max_concurrent", 3),
                poll_interval_seconds=getattr(
                    self._config, "delegation_poll_interval_seconds", 2.0
                ),
                summary_max_chars=getattr(self._config, "delegation_summary_max_chars", 2000),
            )
            kernel = self.build_kernel()

            # Attempt to get an async LLM gateway for child-run summarization.
            # Reuse the cached, fully-wired gateway from build_llm_gateway() to
            # avoid creating a second httpx.AsyncClient pool and a second event-loop
            # binding (Rule 5 cross-loop stability).  TierAwareLLMGateway already
            # implements acomplete() so it satisfies the AsyncLLMGateway surface.
            async_llm: Any | None = None
            try:
                _sync_gw = self.build_llm_gateway()
                async_llm = _sync_gw
            except Exception as _exc:
                logger.debug(
                    "_build_delegation_manager: LLM gateway unavailable (%s), "
                    "child-run summaries will be truncated.",
                    _exc,
                )

            manager = DelegationManager(
                kernel=kernel,
                config=config,
                llm=async_llm,
            )
            logger.info(
                "_build_delegation_manager: DelegationManager created "
                "(max_concurrent=%d, poll_interval=%.1fs).",
                config.max_concurrent,
                config.poll_interval_seconds,
            )
            return manager
        except Exception as exc:
            logger.warning("_build_delegation_manager: failed to create DelegationManager: %s", exc)
            return None

    def _resolve_with_patch(self, patch: dict) -> TraceConfig:
        """Return a new TraceConfig with *patch* merged over self._config.

        When a ConfigStack is available, delegates to it so that all five
        config layers (defaults → file → profile → env → run patch) are
        honoured.  Falls back to a simple merge over the cached config
        otherwise.
        """
        if self._stack is not None:
            return self._stack.resolve(run_patch=patch)
        from dataclasses import asdict
        from dataclasses import fields as dc_fields

        from hi_agent.config.profile import deep_merge

        base = asdict(self._config)
        merged = deep_merge(base, patch)
        known = {f.name for f in dc_fields(TraceConfig)}
        return TraceConfig(**{k: v for k, v in merged.items() if k in known})

    def _build_executor_impl(
        self,
        contract: TaskContract,
        resolved_profile: Any = None,
        workspace_key: Any = None,
    ) -> RunExecutor:
        """Build a fully-wired RunExecutor for a given task contract.

        Args:
            contract: Task contract.
            resolved_profile: Optional ``ResolvedProfile`` from the platform
                ProfileRegistry.  When provided, its stage_graph, stage_actions,
                and evaluator override the TRACE sample defaults.
            workspace_key: Optional ``WorkspaceKey`` (tenant_id, user_id,
                session_id).  When provided, all memory stores are placed under
                workspace-scoped paths instead of the global config directories.
        """
        # DF-27 Rule 13: profile_id is required at the executor-construction layer.
        # The server boundary (handle_create_run) is responsible for assigning the
        # loud-default when the caller supplies none — see Rule 14. At this layer
        # empty profile_id is a contract defect that must be surfaced, not masked.
        _profile_id = getattr(contract, "profile_id", None) or ""
        if not _profile_id:
            raise ValueError(
                "SystemBuilder._build_executor_impl requires a non-empty "
                "contract.profile_id. The server boundary should assign "
                "'default' when the downstream caller does not supply one; "
                "an empty profile_id reaching this layer indicates a skipped "
                "boundary (see DF-27, Rule 13)."
            )

        invoker = self.build_invoker()

        # Pre-compute optional wired components (avoids post-construction mutation).
        _mw = self._build_middleware_orchestrator()
        if _mw is not None:
            self._inject_middleware_dependencies(_mw, profile_id=_profile_id)
            if resolved_profile is not None and resolved_profile.has_evaluator:
                self._inject_evaluator(_mw, resolved_profile)
        _skill_ev = None
        try:
            _skill_ev = self.build_skill_evolver()
        except Exception as exc:
            logger.warning("_build_executor_impl: build_skill_evolver failed: %s", exc)
        _skill_ev_interval = getattr(self._config, "skill_evolve_interval", 10)
        _tracer = None
        try:
            export_dir = getattr(self._config, "trace_export_dir", "")
            if export_dir:
                from hi_agent.observability.tracing import JsonFileTraceExporter, Tracer

                _tracer = Tracer(exporters=[JsonFileTraceExporter(export_dir)])
        except Exception as exc:
            logger.warning("_build_executor_impl: Tracer build failed: %s", exc)

        # Determine stage_graph and stage_actions from profile, falling back to
        # TRACE sample defaults.
        stage_graph: Any | None = None
        stage_actions: dict | None = None
        if resolved_profile is not None:
            if resolved_profile.has_custom_graph:
                stage_graph = resolved_profile.stage_graph
                logger.info(
                    "_build_executor_impl: using profile %r stage_graph.",
                    resolved_profile.profile_id,
                )
            if resolved_profile.has_custom_actions:
                stage_actions = resolved_profile.stage_actions
                logger.info(
                    "_build_executor_impl: using profile %r stage_actions: %s.",
                    resolved_profile.profile_id,
                    list(stage_actions.keys()),
                )

        if resolved_profile is not None and (
            resolved_profile.has_custom_graph or resolved_profile.has_custom_actions
        ):
            logger.info(
                "runtime mode=profile-runtime profile_id=%s "
                "has_custom_graph=%s has_custom_actions=%s",
                resolved_profile.profile_id,
                resolved_profile.has_custom_graph,
                resolved_profile.has_custom_actions,
            )
        else:
            logger.info(
                "runtime mode=trace-sample-fallback (no resolved profile or "
                "profile has no custom topology)"
            )

        # Validate required capabilities are available before building executor.
        if resolved_profile is not None and resolved_profile.required_capabilities:
            self._validate_required_capabilities(resolved_profile)

        # --- Build mid-term / long-term memory components for wiring ---
        _run_id = uuid.uuid4().hex
        # Validate all fields are non-empty before using workspace paths.
        if workspace_key is not None and not (
            workspace_key.tenant_id and workspace_key.user_id and workspace_key.session_id
        ):
            workspace_key = None  # fall back to profile-scoped paths
        if workspace_key is not None:
            from pathlib import Path as _Path

            from hi_agent.server.workspace_path import WorkspacePathHelper

            _raw_base = str(
                WorkspacePathHelper.private(
                    _Path(self._config.episodic_storage_dir).parent,
                    workspace_key,
                    "L0",
                )
            )
            _session_storage_dir = str(
                WorkspacePathHelper.private(
                    _Path(self._config.episodic_storage_dir).parent,
                    workspace_key,
                    "checkpoints",
                )
            )
        else:
            _raw_base = self._config.episodic_storage_dir
            _session_storage_dir = None
        _short_term_store = self.build_short_term_store(
            profile_id=_profile_id, workspace_key=workspace_key
        )
        _mid_term_store = self.build_mid_term_store(
            profile_id=_profile_id, workspace_key=workspace_key
        )
        _long_term_graph = self.build_long_term_graph(
            profile_id=_profile_id, workspace_key=workspace_key
        )
        # J7-1: share the profile-scoped graph with KnowledgeManager.
        km = self.build_knowledge_manager(
            profile_id=_profile_id,
            long_term_graph=_long_term_graph,
        )
        try:
            from hi_agent.memory.long_term import LongTermConsolidator

            _long_term_consolidator = LongTermConsolidator(
                mid_term_store=_mid_term_store,
                graph=_long_term_graph,
            )
        except Exception:
            _long_term_consolidator = None

        executor = RunExecutor(
            contract=contract,
            kernel=self.build_kernel(),
            evolve_engine=self.build_evolve_engine(),
            harness_executor=self.build_harness(capability_invoker=invoker),
            human_gate_quality_threshold=self._config.gate_quality_threshold,
            event_emitter=EventEmitter(),
            # S3: route raw memory construction through the MemoryBuilder
            # registry so parallel callers share the cached per-run_id instance.
            raw_memory=self._get_memory_builder().build_raw_memory_store(
                run_id=_run_id,
                profile_id=_profile_id,
                workspace_key=workspace_key,
            ),
            compressor=self._build_compressor(),
            failure_collector=self.build_failure_collector(),
            watchdog=self.build_watchdog(),
            episode_builder=EpisodeBuilder(),
            episodic_store=self.build_episodic_store(),
            skill_recorder=self._build_skill_recorder(),
            skill_observer=self.build_skill_observer(),
            skill_version_mgr=self.build_skill_version_manager(),
            skill_loader=self.build_skill_loader(),
            state_store=RunStateStore(),
            policy_versions=PolicyVersionSet(),
            route_engine=self._build_route_engine(stage_actions=stage_actions),
            acceptance_policy=AcceptancePolicy(),
            short_term_store=_short_term_store,
            mid_term_store=_mid_term_store,
            long_term_consolidator=_long_term_consolidator,
            knowledge_query_fn=lambda q, **kw: km.query(q, **kw).wiki_pages,
            context_manager=self.build_context_manager(),
            budget_guard=self.build_budget_guard(),
            metrics_collector=self.build_metrics_collector(),
            llm_gateway=self.build_llm_gateway(),
            memory_lifecycle_manager=self.build_memory_lifecycle_manager(
                short_term_store=_short_term_store,
                mid_term_store=_mid_term_store,
                long_term_graph=_long_term_graph,
                profile_id=_profile_id,
            ),
            retrieval_engine=self.build_retrieval_engine(
                short_term_store=_short_term_store,
                mid_term_store=_mid_term_store,
                long_term_graph=_long_term_graph,
                profile_id=_profile_id,
            ),
            tier_router=self._tier_router,
            restart_policy_engine=self._build_restart_policy_engine(),
            reflection_orchestrator=self._build_reflection_orchestrator(),
            delegation_manager=self._build_delegation_manager(),
            stage_graph=stage_graph,  # None → RunExecutor defaults to TRACE graph
            compress_snip_threshold=self._config.compress_snip_threshold,
            compress_window_threshold=self._config.compress_window_threshold,
            compress_compress_threshold=self._config.compress_compress_threshold,
            evolve_mode=getattr(self._config, "evolve_mode", "auto"),
            # Pre-wired components — no post-construction mutation needed.
            middleware_orchestrator=_mw,
            skill_evolver=_skill_ev,
            skill_evolve_interval=_skill_ev_interval,
            tracer=_tracer,
            workspace_key=workspace_key,
            session_storage_dir=_session_storage_dir,
        )
        if _mw is not None:
            logger.info(
                "build_executor: MiddlewareOrchestrator + SkillEvolver + Tracer "
                "wired at construction time (no post-mutation)."
            )
        return executor

    def _inject_evaluator(self, orchestrator: Any, resolved_profile: Any) -> None:
        """Inject profile evaluator into EvaluationMiddleware within the orchestrator."""
        try:
            from hi_agent.evaluation.runtime import EvaluatorRuntime

            runtime = EvaluatorRuntime.from_resolved_profile(resolved_profile)
            middlewares: dict[str, Any] = getattr(orchestrator, "_middlewares", {})
            injected = False
            for mw in middlewares.values():
                if hasattr(mw, "_evaluator"):
                    mw._evaluator = runtime.evaluator
                    injected = True
            if injected:
                logger.info(
                    "_inject_evaluator: evaluator from profile %r injected into "
                    "EvaluationMiddleware.",
                    resolved_profile.profile_id,
                )
        except Exception as exc:
            logger.warning("_inject_evaluator: failed: %s", exc)

    def build_executor(
        self,
        contract: TaskContract,
        config_patch: dict | None = None,
        workspace_key: Any = None,
    ) -> RunExecutor:
        """Build a RunExecutor.

        Resolves ``contract.profile_id`` against the platform ProfileRegistry
        and injects profile-derived stage_graph, stage_actions, and evaluator
        into the executor.  If config_patch provided, creates isolated per-run
        config.

        Args:
            contract: Task contract.
            config_patch: Optional dict of config overrides for this run.
            workspace_key: Optional ``WorkspaceKey`` (tenant_id, user_id,
                session_id).  When provided, all memory stores are placed under
                workspace-scoped paths.
        """
        resolved_profile = self._resolve_profile(getattr(contract, "profile_id", None))
        if config_patch:
            # Merge profile config_overrides into config_patch so profile
            # settings are respected even when the caller also passes a patch.
            if resolved_profile is not None and resolved_profile.config_overrides:
                merged = {**resolved_profile.config_overrides, **config_patch}
            else:
                merged = config_patch
            run_cfg = self._resolve_with_patch(merged)
            derived = SystemBuilder(
                config=run_cfg,
                profile_registry=self.build_profile_registry(),
                capability_registry=self.build_capability_registry(),
                artifact_registry=self.build_artifact_registry(),
            )
            # Inherit cached subsystem singletons so derived builders share
            # the same SkillLoader, MCPRegistry, MCPTransport, PluginLoader, and
            # EvidenceStore instances as the parent — avoids stale subsystems for
            # patched runs and prevents opening duplicate SQLite connections.
            derived._skill_loader = self._skill_loader
            derived._mcp_registry = self._mcp_registry
            derived._mcp_transport = self._mcp_transport
            derived._plugin_loader = self._plugin_loader
            derived._evidence_store = self._evidence_store
            return derived._build_executor_impl(
                contract, resolved_profile=resolved_profile, workspace_key=workspace_key
            )
        elif resolved_profile is not None and resolved_profile.config_overrides:
            run_cfg = self._resolve_with_patch(resolved_profile.config_overrides)
            derived = SystemBuilder(
                config=run_cfg,
                profile_registry=self.build_profile_registry(),
                capability_registry=self.build_capability_registry(),
                artifact_registry=self.build_artifact_registry(),
            )
            # Inherit cached subsystem singletons — same reasoning as above.
            derived._skill_loader = self._skill_loader
            derived._mcp_registry = self._mcp_registry
            derived._mcp_transport = self._mcp_transport
            derived._plugin_loader = self._plugin_loader
            derived._evidence_store = self._evidence_store
            return derived._build_executor_impl(
                contract, resolved_profile=resolved_profile, workspace_key=workspace_key
            )
        return self._build_executor_impl(
            contract, resolved_profile=resolved_profile, workspace_key=workspace_key
        )

    def build_executor_from_checkpoint(self, checkpoint_path: str) -> Callable[[], str]:
        """Build a callable that resumes execution from a checkpoint.

        Args:
            checkpoint_path: Path to the checkpoint JSON file.

        Returns:
            A zero-argument callable that drives the resumed run to
            completion and returns the outcome string.
        """
        import json as _json

        with open(checkpoint_path, encoding="utf-8") as _f:
            _cp_data = _json.load(_f)
        _profile_id = _cp_data.get("task_contract", {}).get("profile_id", "") or ""
        if not _profile_id:
            # DF-27: a checkpoint without profile_id predates Rule 13 or was
            # written via the server boundary's loud-default path. Preserve
            # resumability by adopting the same 'default' label — the server
            # already recorded a fallback event when the run was created.
            _profile_id = "default"
            logger.warning(
                "build_executor_from_checkpoint: checkpoint has no profile_id; "
                "resuming under 'default' (DF-27 parity with server boundary)."
            )

        kernel = self.build_kernel()
        km = self.build_knowledge_manager(
            profile_id=_profile_id,
            long_term_graph=self.build_long_term_graph(
                profile_id=_profile_id, workspace_key=None
            ),
        )

        def resume() -> str:
            return RunExecutor.resume_from_checkpoint(
                checkpoint_path,
                kernel,
                evolve_engine=self.build_evolve_engine(),
                harness_executor=self.build_harness(),
                human_gate_quality_threshold=self._config.gate_quality_threshold,
                event_emitter=EventEmitter(),
                # S3: registry path shares the cached per-profile instance
                # instead of synthesizing a fresh unscoped store.
                raw_memory=self._get_memory_builder().build_raw_memory_store(
                    profile_id=_profile_id,
                ),
                compressor=self._build_compressor(),
                failure_collector=self.build_failure_collector(),
                watchdog=self.build_watchdog(),
                episode_builder=EpisodeBuilder(),
                episodic_store=self.build_episodic_store(),
                skill_recorder=self._build_skill_recorder(),
                skill_observer=self.build_skill_observer(),
                skill_version_mgr=self.build_skill_version_manager(),
                skill_loader=self.build_skill_loader(),
                state_store=RunStateStore(),
                policy_versions=PolicyVersionSet(),
                route_engine=self._build_route_engine(),
                acceptance_policy=AcceptancePolicy(),
                short_term_store=self.build_short_term_store(
                    profile_id=_profile_id, workspace_key=None
                ),
                knowledge_query_fn=lambda q, **kw: km.query(q, **kw).wiki_pages,
                llm_gateway=self.build_llm_gateway(),
            )

        return resume

    def build_orchestrator(self) -> TaskOrchestrator:
        """Build a fully-wired TaskOrchestrator."""
        kernel = self.build_kernel()
        return TaskOrchestrator(kernel=kernel)

    def build_server(self) -> Any:
        """Build API server with all subsystems connected.

        Rule 13 (DF-12) / Rule 6 (K-9): ``memory_manager`` and ``knowledge_manager`` are
        **per-profile** resources and can no longer be pre-built at server
        construction time without a profile_id. Request handlers rebuild them
        per-run using the contract's profile_id (see ``server/routes_memory.py``
        and ``_build_executor_impl`` in this file).
        """
        return self._get_server_builder().build_server(
            skill_evolver=self.build_skill_evolver(),
            skill_loader=self.build_skill_loader(),
            metrics_collector=self.build_metrics_collector(),
            run_context_manager=self._build_run_context_manager(),
        )

    def readiness(self) -> dict[str, Any]:
        """Return a live readiness snapshot of all platform subsystems.

        Delegates to ReadinessProbe — see hi_agent/config/readiness.py.
        """
        from hi_agent.config.readiness import ReadinessProbe

        return ReadinessProbe(self).snapshot()
