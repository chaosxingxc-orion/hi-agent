"""Factory that creates all TRACE subsystems from a single TraceConfig."""

from __future__ import annotations

from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts import TaskContract
from hi_agent.evolve.engine import EvolveEngine
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.harness.executor import HarnessExecutor
from hi_agent.harness.governance import GovernanceEngine
from hi_agent.llm.protocol import LLMGateway
from hi_agent.memory.episodic import EpisodicMemoryStore
from hi_agent.orchestrator.task_orchestrator import TaskOrchestrator
from hi_agent.runner import RunExecutor
from hi_agent.runtime_adapter.mock_kernel import MockKernel
from hi_agent.runtime_adapter.protocol import RuntimeAdapter
from hi_agent.server.app import AgentServer
from hi_agent.server.run_manager import RunManager
from hi_agent.skill.registry import SkillRegistry


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
        """Build kernel adapter (mock for now)."""
        if self._kernel is None:
            self._kernel = MockKernel()
        return self._kernel

    def build_llm_gateway(self) -> LLMGateway | None:
        """Build LLM gateway if an API key is available.

        Returns ``None`` when no key is configured, which lets
        downstream subsystems fall back to heuristic behaviour.
        """
        # LLM gateway requires external provider credentials.  Return
        # None when not available -- subsystems treat this as "no LLM".
        return self._llm_gateway

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

    def build_executor(self, contract: TaskContract) -> RunExecutor:
        """Build a fully-wired RunExecutor for a given task contract."""
        kernel = self.build_kernel()
        return RunExecutor(
            contract=contract,
            kernel=kernel,
            evolve_engine=self.build_evolve_engine(),
            harness_executor=self.build_harness(),
            human_gate_quality_threshold=self._config.gate_quality_threshold,
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
