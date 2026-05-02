"""Simplified facade for RunExecutor and top-level readiness check.

Provides two public surfaces:
- ``RunExecutorFacade``: thin wrapper around RunExecutor with a
  start/run/stop lifecycle suitable for downstream research apps.
- ``check_readiness()``: top-level convenience that delegates to
  ``SystemBuilder.readiness()`` and wraps the result in a
  ``ReadinessReport`` dataclass.
"""

from __future__ import annotations

import logging as _logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = _logging.getLogger(__name__)


@dataclass
class RunFacadeResult:
    """Result returned by :meth:`RunExecutorFacade.run`.

    Attributes:
        success: True when the underlying run status is "completed".
        output: Human-readable outcome description (status string or
            error message).
        run_id: The run_id assigned by the kernel for this execution.
        error: Error detail when ``success`` is False; None otherwise.
    """

    success: bool
    output: str
    run_id: str
    error: str | None = None


@dataclass
class ReadinessReport:
    """Structured readiness snapshot returned by :func:`check_readiness`.

    Attributes:
        ready: True when all critical subsystems are healthy.
        health: "ok" or "degraded".
        subsystems: Per-subsystem status dict as returned by
            ``SystemBuilder.readiness()``.
        auth_posture: Authentication posture.  One of:
            ``"ok"`` — API key is set and enforced;
            ``"dev_risk_open"`` — no key but dev/smoke mode (acceptable);
            ``"degraded"`` — no key in prod-real mode (unacceptable).
    """

    ready: bool
    health: str
    subsystems: dict[str, Any] = field(default_factory=dict)
    auth_posture: str = "unknown"  # "ok" | "dev_risk_open" | "degraded"


class RunExecutorFacade:
    """Simplified facade over :class:`~hi_agent.runner.RunExecutor`.

    Intended for downstream apps that need a minimal start/run/stop
    lifecycle without assembling a full ``TaskContract`` or
    ``SystemBuilder`` themselves.

    Usage::

        facade = RunExecutorFacade()
        facade.start(
            run_id="r-001",
            profile_id="default",
            model_tier="medium",
            skill_dir="./skills",
        )
        result = facade.run("Summarize the TRACE framework")
        facade.stop()
    """

    def __init__(self) -> None:
        """Initialise facade with no active executor."""
        self._executor: Any | None = None
        self._contract: Any | None = None
        self._last_gate_id: str | None = None
        self._last_execution_mode: str = "linear"  # "linear" or "graph"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        run_id: str,
        profile_id: str,
        model_tier: str,
        skill_dir: str | Path,
    ) -> None:
        """Build a configured :class:`~hi_agent.runner.RunExecutor`.

        Constructs a minimal :class:`~hi_agent.contracts.task.TaskContract`
        from the supplied parameters and uses
        :class:`~hi_agent.config.builder.SystemBuilder` to assemble all
        subsystems.  The executor is stored internally for subsequent
        :meth:`run` calls.

        Args:
            run_id: Identifier used as the ``task_id`` of the contract.
            profile_id: Profile to activate via the platform
                ``ProfileRegistry``.
            model_tier: Informational tier hint (``"strong"``,
                ``"medium"``, ``"light"``).  Stored in the contract's
                ``task_family`` field so profile routing can use it.
            skill_dir: Directory containing ``.md`` skill files to pass
                to the ``TraceConfig`` as ``skill_storage_dir``.
        """
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.contracts.task import TaskContract

        cfg = TraceConfig(skill_storage_dir=str(skill_dir))
        contract = TaskContract(
            task_id=run_id,
            goal="",  # overwritten in run()
            profile_id=profile_id,
            task_family=model_tier,
        )
        builder = SystemBuilder(config=cfg)
        self._contract = contract
        self._executor = builder.build_executor(contract)

    def run(self, prompt: str, use_graph: bool = False) -> RunFacadeResult:
        """Execute a single prompt and return a structured result.

        Sets ``contract.goal`` to ``prompt`` then calls
        :meth:`~hi_agent.runner.RunExecutor.execute` (linear) or
        :meth:`~hi_agent.runner.RunExecutor.execute_graph` (DAG) depending
        on ``use_graph``.

        Args:
            prompt: Natural-language task goal.
            use_graph: When True, execute with graph topology so that
                :meth:`continue_from_gate` resumes via the correct
                graph-aware path.

        Returns:
            :class:`RunFacadeResult` with ``success``, ``output``,
            ``run_id``, and optional ``error``.

        Raises:
            RuntimeError: If :meth:`start` has not been called first.
        """
        if self._executor is None or self._contract is None:
            raise RuntimeError("RunExecutorFacade.start() must be called before run().")

        self._contract.goal = prompt
        self._last_execution_mode = "graph" if use_graph else "linear"
        from hi_agent.gate_protocol import GatePendingError

        try:
            run_result = self._executor.execute_graph() if use_graph else self._executor.execute()
        except GatePendingError as _gate_exc:
            self._last_gate_id = getattr(_gate_exc, "gate_id", None)
            raise
        success = str(run_result) == "completed"
        return RunFacadeResult(
            success=success,
            output=str(run_result),
            run_id=run_result.run_id,
            error=run_result.error if not success else None,
        )

    def stop(self) -> None:
        """Tear down the current executor and clear stored state.

        Calls ``_finalize_run("cancelled")`` for resource cleanup before
        clearing the executor reference.

        DF-18 / A-39 (Rule 5 error-visibility): both cleanup steps used to
        log-and-swallow so a partial-cleanup ``stop()`` was externally
        indistinguishable from a clean one. Both steps are still attempted
        independently (one failing must not skip the other), but any
        per-step failure is now also recorded on ``self.last_stop_failures``
        so callers can detect partial cleanup before the next ``start()``.
        """
        failures: list[str] = []
        if self._executor is not None:
            # J9-2: finalize before discarding so resources are cleaned up.
            try:
                finalize_fn = getattr(self._executor, "_finalize_run", None)
                if callable(finalize_fn):
                    finalize_fn("cancelled")
            except Exception as exc:
                _logger.warning("facade.stop: _finalize_run failed: %s", exc)
                failures.append(f"_finalize_run: {exc}")
            try:
                kernel = getattr(self._executor, "kernel", None)
                if kernel is not None and self._contract is not None:
                    cancel_fn = getattr(kernel, "cancel_run", None)
                    if callable(cancel_fn):
                        cancel_fn(self._contract.task_id)
            except Exception as exc:
                _logger.warning("facade.stop: cancel_run failed: %s", exc)
                failures.append(f"cancel_run: {exc}")
        self._executor = None
        self._contract = None
        self.last_stop_failures: list[str] = failures

    @property
    def last_gate_id(self) -> str | None:
        """The gate_id from the most recent GatePendingError raised by run().

        Returns None if no gate has been raised in the current run.
        """
        return self._last_gate_id

    def continue_from_gate(
        self,
        gate_id: str,
        decision: str,
        rationale: str = "",
    ) -> RunFacadeResult:
        """Resume execution after a human gate decision.

        Args:
            gate_id: Gate identifier — use :attr:`last_gate_id` if unsure.
            decision: ``"approved"``, ``"override"``, or ``"backtrack"``.
            rationale: Free-text rationale (optional).

        Returns:
            :class:`RunFacadeResult` with the post-gate run outcome.

        Raises:
            RuntimeError: If :meth:`start` has not been called first.
            GatePendingError: If another gate fires during resumed execution.
        """
        if self._executor is None:
            raise RuntimeError(
                "RunExecutorFacade.start() must be called before continue_from_gate()."
            )
        from hi_agent.gate_protocol import GatePendingError

        try:
            if self._last_execution_mode == "graph":
                run_result = self._executor.continue_from_gate_graph(
                    gate_id=gate_id,
                    decision=decision,
                    rationale=rationale,
                )
            else:
                run_result = self._executor.continue_from_gate(
                    gate_id=gate_id,
                    decision=decision,
                    rationale=rationale,
                )
        except GatePendingError as _gate_exc:
            self._last_gate_id = getattr(_gate_exc, "gate_id", None)
            raise
        success = str(run_result) == "completed"
        return RunFacadeResult(
            success=success,
            output=str(run_result),
            run_id=run_result.run_id,
            error=run_result.error if not success else None,
        )


# ---------------------------------------------------------------------------
# Top-level readiness helper
# ---------------------------------------------------------------------------


def check_readiness() -> ReadinessReport:
    """Return a live readiness snapshot of all platform subsystems.

    Delegates to :meth:`~hi_agent.config.builder.SystemBuilder.readiness`
    and wraps the result in a :class:`ReadinessReport` for typed access.

    Never raises — subsystem failures are captured inside
    ``ReadinessReport.subsystems``.

    Returns:
        :class:`ReadinessReport` with ``ready``, ``health``,
        ``subsystems``, and ``auth_posture`` populated.
    """
    import os as _os_cr

    from hi_agent.config.builder import SystemBuilder
    from hi_agent.server.auth_middleware import AuthMiddleware
    from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm

    builder = SystemBuilder()
    raw = builder.readiness()

    # Compute auth posture using a temporary AuthMiddleware instance (no-op app).
    _env_cr = _os_cr.environ.get("HI_AGENT_ENV", "dev").lower()
    _runtime_mode_cr = _rrm(_env_cr, raw)
    _auth = AuthMiddleware(app=lambda *a: None, runtime_mode=_runtime_mode_cr)  # type: ignore[arg-type]  expiry_wave: permanent
    posture = _auth.auth_posture

    return ReadinessReport(
        ready=bool(raw.get("ready", False)),
        health=str(raw.get("health", "degraded")),
        subsystems=dict(raw.get("subsystems", {})),
        auth_posture=posture,
    )
