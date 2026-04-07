"""Factory that creates all TRACE subsystems from a single TraceConfig."""

from __future__ import annotations

import os
from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import TaskContract
from hi_agent.contracts.policy import PolicyVersionSet
from hi_agent.events import EventEmitter
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine
from hi_agent.llm.http_gateway import HttpLLMGateway
from hi_agent.llm.protocol import LLMGateway
from hi_agent.memory import MemoryCompressor, RawMemoryStore
from hi_agent.memory.episode_builder import EpisodeBuilder
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.orchestrator.task_orchestrator import TaskOrchestrator
from hi_agent.route_engine.acceptance import AcceptancePolicy
from hi_agent.route_engine.hybrid_engine import HybridRouteEngine
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient
from hi_agent.runtime_adapter.mock_kernel import MockKernel
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.server.app import AgentServer
from hi_agent.server.dream_scheduler import MemoryLifecycleManager
from hi_agent.server.run_manager import RunManager
from hi_agent.skill.matcher import SkillMatcher
from hi_agent.skill.recorder import SkillUsageRecorder
from hi_agent.skill.registry import SkillRegistry
from hi_agent.state import RunStateStore


class SystemBuilder:
    """Factory that creates all TRACE subsystems from a single TraceConfig.

    This is the main assembly point -- creates properly configured
    instances of all subsystems and wires them together.
    """

    def __init__(self, config: TraceConfig) -> None:
        self._config = config
        # Cache built singletons so repeated calls return the same instance.
        self._kernel: RuntimeAdapter | None = None
        self._llm_gateway: LLMGateway | None = None

    # ------------------------------------------------------------------
    # Individual builders
    # ------------------------------------------------------------------

    def build_kernel(self) -> RuntimeAdapter:
        """Build kernel adapter.

        When ``config.kernel_base_url`` is set and is not ``"mock"``,
        creates a :class:`KernelFacadeClient` in HTTP mode.
        Otherwise falls back to :class:`MockKernel`.
        """
        if self._kernel is None:
            base_url = self._config.kernel_base_url
            if base_url and base_url.lower() != "mock":
                self._kernel = KernelFacadeClient(
                    mode="http",
                    base_url=base_url,
                    timeout_seconds=30,
                )
            else:
                self._kernel = MockKernel()
        return self._kernel

    def build_llm_gateway(self) -> LLMGateway | None:
        """Build LLM gateway -- auto-activates if API key found in env.

        Checks for known provider API keys in the environment and
        creates an :class:`HttpLLMGateway` for the first match.
        Returns ``None`` when no key is configured, which lets
        downstream subsystems fall back to heuristic behaviour.
        """
        if self._llm_gateway is not None:
            return self._llm_gateway

        for env_var, base_url, default_model in [
            (
                self._config.openai_api_key_env,
                self._config.openai_base_url,
                self._config.openai_default_model,
            ),
            (
                self._config.anthropic_api_key_env,
                self._config.anthropic_base_url + "/v1",
                self._config.anthropic_default_model,
            ),
        ]:
            if os.environ.get(env_var):
                self._llm_gateway = HttpLLMGateway(
                    base_url=base_url,
                    api_key_env=env_var,
                    default_model=default_model,
                    timeout_seconds=self._config.llm_timeout_seconds,
                )
                return self._llm_gateway

        return None  # No API key found, LLM features disabled

    def build_evolve_engine(self) -> EvolveEngine:
        """Build EvolveEngine with config-driven parameters."""
        from hi_agent.evolve.regression_detector import RegressionDetector
        from hi_agent.evolve.skill_extractor import SkillExtractor

        gateway = self.build_llm_gateway()
        return EvolveEngine(
            llm_gateway=gateway,
            skill_extractor=SkillExtractor(
                min_confidence=self._config.evolve_min_confidence,
                gateway=gateway,
            ),
            regression_detector=RegressionDetector(
                baseline_window=self._config.evolve_regression_window,
                threshold=self._config.evolve_regression_threshold,
            ),
        )

    def build_harness(self) -> HarnessExecutor:
        """Build HarnessExecutor with config-driven governance."""
        governance = GovernanceEngine()
        return HarnessExecutor(
            governance=governance,
        )

    def build_skill_registry(self) -> SkillRegistry:
        """Build SkillRegistry using configured storage directory."""
        return SkillRegistry(storage_dir=self._config.skill_storage_dir)

    def build_episodic_store(self) -> EpisodicMemoryStore:
        """Build EpisodicMemoryStore using configured storage directory."""
        return EpisodicMemoryStore(storage_dir=self._config.episodic_storage_dir)

    def build_failure_collector(self) -> FailureCollector:
        """Build a fresh FailureCollector."""
        return FailureCollector()

    def build_watchdog(self) -> ProgressWatchdog:
        """Build ProgressWatchdog with config-driven thresholds."""
        return ProgressWatchdog(
            window_size=self._config.watchdog_window_size,
            min_success_rate=self._config.watchdog_min_success_rate,
            max_consecutive_failures=self._config.watchdog_max_consecutive_failures,
        )

    # ------------------------------------------------------------------
    # Memory tier builders
    # ------------------------------------------------------------------

    def build_short_term_store(self) -> Any:
        """Build short-term memory store."""
        from hi_agent.memory.short_term import ShortTermMemoryStore

        return ShortTermMemoryStore(
            self._config.episodic_storage_dir.replace("episodes", "short_term")
        )

    def build_mid_term_store(self) -> Any:
        """Build mid-term memory store."""
        from hi_agent.memory.mid_term import MidTermMemoryStore

        return MidTermMemoryStore(
            self._config.episodic_storage_dir.replace("episodes", "mid_term")
        )

    def build_long_term_graph(self) -> Any:
        """Build long-term memory graph."""
        from hi_agent.memory.long_term import LongTermMemoryGraph

        return LongTermMemoryGraph(
            self._config.episodic_storage_dir.replace(
                "episodes", "long_term/graph.json"
            )
        )

    def build_retrieval_engine(self) -> Any:
        """Build four-layer retrieval engine across all memory tiers."""
        from hi_agent.knowledge.retrieval_engine import RetrievalEngine

        wiki = self.build_knowledge_wiki()
        graph = self.build_long_term_graph()
        short = self.build_short_term_store()
        mid = self.build_mid_term_store()
        return RetrievalEngine(
            wiki=wiki, graph=graph, short_term=short, mid_term=mid
        )

    def build_memory_lifecycle_manager(self) -> MemoryLifecycleManager:
        """Build MemoryLifecycleManager wiring all memory tiers."""
        return MemoryLifecycleManager(
            short_term_store=self.build_short_term_store(),
            mid_term_store=self.build_mid_term_store(),
            long_term_graph=self.build_long_term_graph(),
            retrieval_engine=self.build_retrieval_engine(),
        )

    # ------------------------------------------------------------------
    # Knowledge tier builders
    # ------------------------------------------------------------------

    def build_knowledge_wiki(self) -> Any:
        """Build KnowledgeWiki for wiki-based knowledge storage."""
        from hi_agent.knowledge.wiki import KnowledgeWiki

        base = self._config.episodic_storage_dir.replace("episodes", "")
        return KnowledgeWiki(os.path.join(base, "knowledge", "wiki"))

    def build_user_knowledge_store(self) -> Any:
        """Build UserKnowledgeStore for user profile knowledge."""
        from hi_agent.knowledge.user_knowledge import UserKnowledgeStore

        base = self._config.episodic_storage_dir.replace("episodes", "")
        return UserKnowledgeStore(os.path.join(base, "knowledge", "user"))

    def build_knowledge_manager(self) -> Any:
        """Build KnowledgeManager wiring wiki, user store, graph, and renderer."""
        from hi_agent.knowledge.knowledge_manager import KnowledgeManager
        from hi_agent.knowledge.graph_renderer import GraphRenderer

        wiki = self.build_knowledge_wiki()
        user_store = self.build_user_knowledge_store()
        graph = self.build_long_term_graph()
        renderer = GraphRenderer(graph)
        return KnowledgeManager(
            wiki=wiki, user_store=user_store, graph=graph, renderer=renderer,
        )

    # ------------------------------------------------------------------
    # Composite builders
    # ------------------------------------------------------------------

    def _build_compressor(self) -> MemoryCompressor:
        """Create MemoryCompressor, wiring LLM gateway if available."""
        return MemoryCompressor(
            gateway=self.build_llm_gateway(),
            compress_threshold=self._config.memory_compress_threshold,
            timeout_s=self._config.memory_compress_timeout_seconds,
            fallback_items=self._config.memory_compress_fallback_items,
        )

    def _build_route_engine(self) -> HybridRouteEngine:
        """Create HybridRouteEngine with LLM gateway + SkillMatcher if available."""
        registry = self.build_skill_registry()
        gateway = self.build_llm_gateway()
        matcher = SkillMatcher(registry=registry) if registry else None
        return HybridRouteEngine(
            gateway=gateway,
            skill_matcher=matcher,
            confidence_threshold=self._config.route_confidence_threshold,
        )

    def _build_skill_recorder(self) -> SkillUsageRecorder:
        """Create SkillUsageRecorder with the skill registry."""
        return SkillUsageRecorder(registry=self.build_skill_registry())

    def build_executor(self, contract: TaskContract) -> RunExecutor:
        """Build a fully-wired RunExecutor for a given task contract."""
        km = self.build_knowledge_manager()
        return RunExecutor(
            contract=contract,
            kernel=self.build_kernel(),
            evolve_engine=self.build_evolve_engine(),
            harness_executor=self.build_harness(),
            human_gate_quality_threshold=self._config.gate_quality_threshold,
            event_emitter=EventEmitter(),
            raw_memory=RawMemoryStore(),
            compressor=self._build_compressor(),
            failure_collector=self.build_failure_collector(),
            watchdog=self.build_watchdog(),
            episode_builder=EpisodeBuilder(),
            episodic_store=self.build_episodic_store(),
            skill_recorder=self._build_skill_recorder(),
            state_store=RunStateStore(),
            policy_versions=PolicyVersionSet(),
            route_engine=self._build_route_engine(),
            acceptance_policy=AcceptancePolicy(),
            short_term_store=self.build_short_term_store(),
            knowledge_query_fn=lambda q, **kw: km.query(q, **kw).wiki_pages,
        )

    def build_orchestrator(self) -> TaskOrchestrator:
        """Build a fully-wired TaskOrchestrator."""
        kernel = self.build_kernel()
        return TaskOrchestrator(kernel=kernel)

    def build_server(self) -> AgentServer:
        """Build API server with all subsystems connected."""
        server = AgentServer(
            host=self._config.server_host,
            port=self._config.server_port,
        )
        server.run_manager = RunManager(
            max_concurrent=self._config.server_max_concurrent_runs,
        )
        server.memory_manager = self.build_memory_lifecycle_manager()
        server.knowledge_manager = self.build_knowledge_manager()
        return server
