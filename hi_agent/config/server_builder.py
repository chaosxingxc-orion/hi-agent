"""Factory for constructing and wiring AgentServer instances."""

from __future__ import annotations

import logging
from typing import Any

from hi_agent.config.trace_config import TraceConfig
from hi_agent.observability.metric_counter import Counter
from hi_agent.server.app import AgentServer
from hi_agent.server.run_manager import RunManager

logger = logging.getLogger(__name__)
_server_builder_errors_total = Counter("hi_agent_server_builder_errors_total")


class ServerBuilder:
    """Build API server instances from TraceConfig and injected subsystems."""

    def __init__(self, config: TraceConfig) -> None:
        self._config = config

    def build_server(self, **kwargs: Any) -> Any:
        """Build an AgentServer and wire provided subsystem instances onto it."""
        build_kwargs = dict(kwargs)
        host = build_kwargs.pop("host", self._config.server_host)
        port = build_kwargs.pop("port", self._config.server_port)
        constructor_kwargs: dict[str, Any] = {}
        for name in ("config", "rate_limit_rps", "profile_registry"):
            if name in build_kwargs:
                constructor_kwargs[name] = build_kwargs.pop(name)

        server = AgentServer(host=host, port=port, **constructor_kwargs)
        server.run_manager = RunManager(
            max_concurrent=self._config.server_max_concurrent_runs,
        )

        for attr in (
            "memory_manager",
            "knowledge_manager",
            "skill_evolver",
            "skill_loader",
            "run_context_manager",
        ):
            if attr in build_kwargs:
                setattr(server, attr, build_kwargs[attr])

        if "metrics_collector" in build_kwargs:
            metrics = build_kwargs["metrics_collector"]
            server.metrics_collector = metrics
            if metrics is not None:
                try:
                    from hi_agent.management.slo import SLOMonitor

                    server.slo_monitor = SLOMonitor(metrics)
                except Exception as exc:
                    _server_builder_errors_total.inc()
                    logger.warning(
                        "SLOMonitor initialization failed (%s: %s); SLO monitoring disabled.",
                        type(exc).__name__,
                        exc,
                    )

        return server
