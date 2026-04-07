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
            ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o"),
            ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-20250514"),
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
        return EvolveEngine(
            llm_gateway=self.build_llm_gateway(),
        )

    def build_harness(self) -> HarnessExecutor:
        """Build HarnessExecutor with config-driven governance."""
        governance = GovernanceEngine()
        return HarnessExecutor(governance=governance)

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
    # Composite builders
    # ------------------------------------------------------------------

    def _build_compressor(self) -> MemoryCompressor:
        """Create MemoryCompressor, wiring LLM gateway if available."""
        return MemoryCompressor(gateway=self.build_llm_gateway())

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
        return server
