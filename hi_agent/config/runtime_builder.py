"""RuntimeBuilder: kernel, metrics, middleware, and executor assembly (HI-W10-002).

Extracted from SystemBuilder to reduce builder.py god-object footprint.
Holds all kernel adapter, metrics collector, middleware orchestrator,
and executor construction logic.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.observability.collector import MetricsCollector
    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

_logger = logging.getLogger(__name__)


class RuntimeBuilder:
    """Builds kernel adapter, metrics, middleware orchestrator, and executors.

    Receives *config*, *singleton_lock*, and a *parent* reference to the
    owning SystemBuilder so that cross-subsystem build_* calls (e.g.
    build_llm_gateway inside build_executor) can be resolved without
    duplicating logic.
    """

    def __init__(
        self,
        config: TraceConfig,
        singleton_lock: Any,
        parent: Any,  # SystemBuilder — avoids circular import at module level
    ) -> None:
        self._config = config
        self._lock = singleton_lock
        self._parent = parent
        # Cached singletons
        self._kernel: RuntimeAdapter | None = None
        self._metrics_collector: MetricsCollector | None = None
        self._run_context_manager: Any | None = None
        self._middleware_orchestrator: Any | None = None

    # ------------------------------------------------------------------
    # Kernel
    # ------------------------------------------------------------------

    def build_kernel(self) -> RuntimeAdapter:
        """Build kernel adapter (HTTP or in-process LocalFSM)."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import create_local_adapter
        from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient

        with self._lock:
            if self._kernel is None:
                base_url = self._config.kernel_base_url
                env = os.environ.get("HI_AGENT_ENV", "dev").lower()
                if base_url and base_url.lower() == "mock":
                    raise ValueError(
                        "kernel_base_url='mock' is no longer supported. "
                        "Use 'local' for in-process agent-kernel LocalFSM, "
                        "or set a real http(s) agent-kernel endpoint."
                    )
                if env == "prod" and (not base_url or base_url.lower() == "local"):
                    _logger.warning(
                        "Production mode with kernel_base_url=%r — "
                        "using in-process LocalFSM kernel. "
                        "For full multi-process production deploy, set "
                        "HI_AGENT_KERNEL_BASE_URL to a real agent-kernel endpoint.",
                        base_url,
                    )
                if base_url and base_url.lower() != "local":
                    self._kernel = KernelFacadeClient(
                        mode="http",
                        base_url=base_url,
                        timeout_seconds=30,
                    )
                else:
                    _logger.warning(
                        "build_kernel: kernel_base_url=%r — using in-process LocalFSM. "
                        "Set kernel_base_url to a real agent-kernel HTTP endpoint for production.",
                        base_url,
                    )
                    self._kernel = create_local_adapter()
                from hi_agent.runtime_adapter import ResilientKernelAdapter

                self._kernel = ResilientKernelAdapter(
                    self._kernel,
                    max_retries=self._config.kernel_max_retries,
                )
        return self._kernel

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def build_metrics_collector(self) -> MetricsCollector:
        """Build or return the shared MetricsCollector singleton."""
        from hi_agent.observability.collector import MetricsCollector, default_alert_rules

        with self._lock:
            if self._metrics_collector is None:
                self._metrics_collector = MetricsCollector()
                for rule in default_alert_rules():
                    self._metrics_collector.add_alert_rule(rule)
                _webhook_url = os.environ.get("WEBHOOK_URL", "")
                if _webhook_url:
                    import time as _time

                    from hi_agent.observability.notification import (
                        build_notification_backend,
                        send_notification,
                    )

                    _backend = build_notification_backend(_webhook_url)

                    def _alert_cb(alert: object) -> None:
                        _alert_name = getattr(alert, "rule_name", str(alert))
                        _metric_name = getattr(alert, "metric_name", "")
                        _value = getattr(alert, "current_value", 0.0)
                        send_notification(
                            backend=_backend,
                            event=f"alert.{_alert_name}",
                            severity="warning",
                            message=f"Alert {_alert_name}: {_metric_name}={_value:.3f}",
                            context={
                                "alert_name": _alert_name,
                                "metric_name": _metric_name,
                                "value": _value,
                            },
                            timestamp=_time.time(),
                        )

                    self._metrics_collector.set_alert_callback(_alert_cb)
        return self._metrics_collector

    # ------------------------------------------------------------------
    # Run context + middleware
    # ------------------------------------------------------------------

    def build_run_context_manager(self) -> Any:
        """Build or return the shared RunContextManager singleton."""
        with self._lock:
            if self._run_context_manager is None:
                try:
                    from hi_agent.context.run_context import RunContextManager

                    self._run_context_manager = RunContextManager()
                    _logger.info("build_run_context_manager: RunContextManager created.")
                except Exception as exc:
                    _logger.warning(
                        "build_run_context_manager: failed to create RunContextManager: %s", exc
                    )
        return self._run_context_manager

    def build_middleware_orchestrator(self) -> Any:
        """Build or return the shared MiddlewareOrchestrator singleton."""
        if self._middleware_orchestrator is None:
            try:
                from hi_agent.middleware.defaults import create_default_orchestrator

                gateway = self._parent.build_llm_gateway()
                self._middleware_orchestrator = create_default_orchestrator(
                    llm_gateway=gateway,
                    quality_threshold=getattr(self._config, "gate_quality_threshold", 0.7),
                    summary_threshold=getattr(
                        self._config, "perception_summary_threshold_tokens", 2000
                    ),
                    max_entities=getattr(self._config, "perception_max_entities", 50),
                    llm_summarize_char_threshold=getattr(
                        self._config, "perception_summarize_char_threshold", 500
                    ),
                    summarize_temperature=getattr(
                        self._config, "perception_summarize_temperature", 0.3
                    ),
                    summarize_max_tokens=getattr(
                        self._config, "perception_summarize_max_tokens", 200
                    ),
                )
                _logger.info("build_middleware_orchestrator: MiddlewareOrchestrator created.")
            except Exception as exc:
                _logger.warning(
                    "build_middleware_orchestrator: failed to create MiddlewareOrchestrator: %s",
                    exc,
                )
        return self._middleware_orchestrator

    def inject_middleware_dependencies(self, orchestrator: Any, *, profile_id: str) -> None:
        """Post-inject subsystem dependencies into orchestrator's middleware instances.

        Called after all subsystems are available so the orchestrator's
        middleware instances get their context_manager, skill_loader, etc.

        Rule 13 (DF-27): ``profile_id`` is required so knowledge / retrieval
        builders can scope their stores. Callers should already have raised
        when profile_id is empty; we guard here as a defence-in-depth.
        """
        if not profile_id:
            raise ValueError(
                "inject_middleware_dependencies requires a non-empty profile_id "
                "(DF-27 / Rule 13)."
            )
        try:
            middlewares: dict[str, Any] = getattr(orchestrator, "_middlewares", {})
            if not middlewares:
                return
            context_mgr = self._parent.build_context_manager()
            skill_ldr = self._parent.build_skill_loader()
            knowledge_mgr = self._parent.build_knowledge_manager(profile_id=profile_id)
            retrieval_eng = self._parent.build_retrieval_engine(profile_id=profile_id)
            harness = self._parent.build_harness()
            capability_inv = self._parent.build_invoker()

            attr_subsystems: list[tuple[str, Any]] = [
                ("_context_manager", context_mgr),
                ("_skill_loader", skill_ldr),
                ("_knowledge_manager", knowledge_mgr),
                ("_retrieval_engine", retrieval_eng),
                ("_harness_executor", harness),
                ("_capability_invoker", capability_inv),
            ]

            injected: list[str] = []
            for mw_name, mw in middlewares.items():
                for attr, value in attr_subsystems:
                    if hasattr(mw, attr) and getattr(mw, attr) is None and value is not None:
                        setattr(mw, attr, value)
                        injected.append(f"{mw_name}.{attr}")
            if injected:
                _logger.info(
                    "inject_middleware_dependencies: injected into [%s].",
                    ", ".join(injected),
                )
        except Exception as exc:
            _logger.warning(
                "inject_middleware_dependencies: failed, middleware may run degraded: %s", exc
            )

    def build_restart_policy_engine(self) -> Any | None:
        """Build RestartPolicyEngine with no-op stub collaborators."""
        try:
            from hi_agent.task_mgmt.restart_policy import RestartPolicyEngine, TaskRestartPolicy

            _default_policy = TaskRestartPolicy(
                max_attempts=getattr(self._config, "restart_max_attempts", 3),
                backoff_base_ms=2000,
                on_exhausted=getattr(self._config, "restart_on_exhausted", "reflect"),
            )
            _attempt_store: dict[str, list[Any]] = {}
            _state_store: dict[str, Any] = {}
            engine = RestartPolicyEngine(
                get_attempts=lambda task_id: list(_attempt_store.get(task_id, [])),
                get_policy=lambda task_id: _default_policy,
                update_state=lambda task_id, state: _state_store.update({task_id: state}),
                record_attempt=lambda attempt: _attempt_store.setdefault(
                    getattr(attempt, "task_id", ""), []
                ).append(attempt),
            )
            _logger.info(
                "build_restart_policy_engine: RestartPolicyEngine created "
                "(max_attempts=%s, on_exhausted=%s).",
                _default_policy.max_attempts,
                _default_policy.on_exhausted,
            )
            return engine
        except Exception as exc:
            _logger.warning(
                "build_restart_policy_engine: failed to create RestartPolicyEngine: %s", exc
            )
            return None
