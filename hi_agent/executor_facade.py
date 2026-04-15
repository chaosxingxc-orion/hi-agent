"""Simplified facade for RunExecutor and top-level readiness check.

Provides two public surfaces:
- ``RunExecutorFacade``: thin wrapper around RunExecutor with a
  start/run/stop lifecycle suitable for downstream research apps.
- ``check_readiness()``: top-level convenience that delegates to
  ``SystemBuilder.readiness()`` and wraps the result in a
  ``ReadinessReport`` dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    """

    ready: bool
    health: str
    subsystems: dict[str, Any] = field(default_factory=dict)


class RunExecutorFacade:
    """Simplified facade over :class:`~hi_agent.runner.RunExecutor`.

    Intended for downstream apps that need a minimal start/run/stop
    lifecycle without assembling a full ``TaskContract`` or
    ``SystemBuilder`` themselves.

    Usage::

        facade = RunExecutorFacade()
        facade.start(
            run_id="r-001",
            profile_id="research",
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

    def run(self, prompt: str) -> RunFacadeResult:
        """Execute a single prompt and return a structured result.

        Sets ``contract.goal`` to ``prompt`` then calls
        :meth:`~hi_agent.runner.RunExecutor.execute`.

        Args:
            prompt: Natural-language task goal.

        Returns:
            :class:`RunFacadeResult` with ``success``, ``output``,
            ``run_id``, and optional ``error``.

        Raises:
            RuntimeError: If :meth:`start` has not been called first.
        """
        if self._executor is None or self._contract is None:
            raise RuntimeError(
                "RunExecutorFacade.start() must be called before run()."
            )

        self._contract.goal = prompt
        run_result = self._executor.execute()
        success = str(run_result) == "completed"
        return RunFacadeResult(
            success=success,
            output=str(run_result),
            run_id=run_result.run_id,
            error=run_result.error if not success else None,
        )

    def stop(self) -> None:
        """Tear down the current executor and clear stored state.

        A best-effort cancel is issued to the kernel adapter when
        available; failures are silently swallowed so callers do not need
        to handle cleanup errors.
        """
        if self._executor is not None:
            try:
                kernel = getattr(self._executor, "kernel", None)
                if kernel is not None and self._contract is not None:
                    cancel_fn = getattr(kernel, "cancel_run", None)
                    if callable(cancel_fn):
                        cancel_fn(self._contract.task_id)
            except Exception:
                pass
        self._executor = None
        self._contract = None


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
        :class:`ReadinessReport` with ``ready``, ``health``, and
        ``subsystems`` populated.
    """
    from hi_agent.config.builder import SystemBuilder

    builder = SystemBuilder()
    raw = builder.readiness()
    return ReadinessReport(
        ready=bool(raw.get("ready", False)),
        health=str(raw.get("health", "degraded")),
        subsystems=dict(raw.get("subsystems", {})),
    )
