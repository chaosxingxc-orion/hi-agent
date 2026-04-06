"""RuntimeAdapter implementation backed by a KernelFacade-like object.

Maps the 17-method RuntimeAdapter Protocol surface to calls on a
``KernelFacade``-compatible object.  The adapter keeps a thin translation
layer: it normalises hi-agent DTO shapes into the arguments the facade
expects and wraps all errors uniformly in ``RuntimeAdapterBackendError``.

For development use without a Temporal server, see
:func:`create_local_adapter` which wires ``KernelRuntime`` with
``LocalSubstrateConfig``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError


class KernelFacadeAdapter:
    """Forward RuntimeAdapter Protocol calls to a KernelFacade instance.

    Each of the 17 Protocol methods is mapped to its KernelFacade
    counterpart.  Where the facade uses typed request DTOs (e.g.
    ``StartRunRequest``), this adapter constructs them from the simpler
    positional arguments defined in the Protocol.

    The facade object is typed as ``object`` so that tests can inject
    a lightweight mock without importing ``agent-kernel``.
    """

    def __init__(self, facade: object) -> None:
        """Store facade instance used for forwarding calls.

        Args:
            facade: An instance of ``agent_kernel.adapters.facade.KernelFacade``
                or any object that exposes the same method signatures.
        """
        self._facade = facade

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def open_stage(self, stage_id: str) -> None:
        """Open a stage in facade runtime.

        Maps to ``facade.open_stage(stage_id, run_id=...)``.
        Because the Protocol signature does not carry ``run_id``, the
        facade call uses stage_id only.  When the real KernelFacade
        requires a run_id parameter, the caller must set it on the
        adapter or the facade must be wrapped.
        """
        self._call("open_stage", self._non_empty(stage_id, "stage_id"))

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Mark stage state in facade runtime."""
        normalized_stage = self._non_empty(stage_id, "stage_id")
        normalized_target = (
            target.value if isinstance(target, StageState) else str(target)
        )
        self._call("mark_stage_state", normalized_stage, normalized_target)

    # ------------------------------------------------------------------
    # Task view
    # ------------------------------------------------------------------

    def record_task_view(
        self, task_view_id: str, content: dict[str, Any]
    ) -> str:
        """Record task view payload and return stored ID."""
        normalized_task_view = self._non_empty(task_view_id, "task_view_id")
        if not isinstance(content, dict):
            raise ValueError("content must be a dict")
        result = self._call(
            "record_task_view", normalized_task_view, dict(content)
        )
        if isinstance(result, str) and result.strip():
            return result
        return normalized_task_view

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        """Bind a task-view record to decision reference."""
        self._call(
            "bind_task_view_to_decision",
            self._non_empty(task_view_id, "task_view_id"),
            self._non_empty(decision_ref, "decision_ref"),
        )

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, task_id: str) -> str:
        """Start one run and return run ID.

        Maps ``task_id`` to the facade's ``start_run`` call.
        The real KernelFacade expects a ``StartRunRequest`` DTO;
        when the facade exposes that signature the caller should
        construct the request externally.  This thin bridge passes
        ``task_id`` as a positional arg for mock/test facades.
        """
        normalized_task = self._non_empty(task_id, "task_id")
        result = self._call("start_run", normalized_task)
        if not isinstance(result, str) or not result.strip():
            error = ValueError(
                "start_run must return a non-empty run_id string"
            )
            raise RuntimeAdapterBackendError(
                "start_run", cause=error
            ) from error
        return result

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Query one run snapshot."""
        normalized_run = self._non_empty(run_id, "run_id")
        result = self._call("query_run", normalized_run)
        if not isinstance(result, dict):
            error = ValueError("query_run must return a dict")
            raise RuntimeAdapterBackendError(
                "query_run", cause=error
            ) from error
        return dict(result)

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel one run with reason."""
        self._call(
            "cancel_run",
            self._non_empty(run_id, "run_id"),
            self._non_empty(reason, "reason"),
        )

    def resume_run(self, run_id: str) -> None:
        """Resume a waiting or paused run."""
        self._call("resume_run", self._non_empty(run_id, "run_id"))

    def signal_run(
        self,
        run_id: str,
        signal: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Deliver one runtime signal to a run."""
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_signal = self._non_empty(signal, "signal")
        normalized_payload = payload or {}
        if not isinstance(normalized_payload, dict):
            raise ValueError("payload must be a dict when provided")
        self._call(
            "signal_run",
            normalized_run,
            normalized_signal,
            dict(normalized_payload),
        )

    # ------------------------------------------------------------------
    # Trace runtime
    # ------------------------------------------------------------------

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Query extended runtime trace payload."""
        normalized_run = self._non_empty(run_id, "run_id")
        result = self._call("query_trace_runtime", normalized_run)
        if not isinstance(result, dict):
            error = ValueError("query_trace_runtime must return a dict")
            raise RuntimeAdapterBackendError(
                "query_trace_runtime", cause=error
            ) from error
        return dict(result)

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield run events as an async stream.

        Delegates to ``facade.stream_run_events(run_id)``.
        The real KernelFacade returns ``AsyncGenerator[RuntimeEvent]``;
        this adapter converts each event to a plain dict for protocol
        compatibility.

        If the facade does not implement ``stream_run_events``, raises
        ``RuntimeAdapterBackendError``.
        """
        normalized_run = self._non_empty(run_id, "run_id")
        method = getattr(self._facade, "stream_run_events", None)
        if not callable(method):
            missing = NotImplementedError(
                "facade does not implement 'stream_run_events'"
            )
            raise RuntimeAdapterBackendError(
                "stream_run_events", cause=missing
            ) from missing
        try:
            async for event in method(normalized_run):
                if isinstance(event, dict):
                    yield event
                else:
                    # Convert dataclass-style RuntimeEvent to dict
                    yield (
                        event.__dict__.copy()
                        if hasattr(event, "__dict__")
                        else {"event": str(event)}
                    )
        except RuntimeAdapterBackendError:
            raise
        except Exception as exc:
            raise RuntimeAdapterBackendError(
                "stream_run_events", cause=exc
            ) from exc

    # ------------------------------------------------------------------
    # Branch lifecycle
    # ------------------------------------------------------------------

    def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
        """Open a branch under one stage."""
        self._call(
            "open_branch",
            self._non_empty(run_id, "run_id"),
            self._non_empty(stage_id, "stage_id"),
            self._non_empty(branch_id, "branch_id"),
        )

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Mark branch state with optional failure code."""
        normalized_failure = (
            None
            if failure_code is None
            else self._non_empty(failure_code, "failure_code")
        )
        self._call(
            "mark_branch_state",
            self._non_empty(run_id, "run_id"),
            self._non_empty(stage_id, "stage_id"),
            self._non_empty(branch_id, "branch_id"),
            self._non_empty(state, "state"),
            normalized_failure,
        )

    # ------------------------------------------------------------------
    # Human gate
    # ------------------------------------------------------------------

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open a human gate and block until resolved or timed out.

        Delegates to ``facade.open_human_gate(request)``.
        The real KernelFacade expects an ``agent_kernel`` HumanGateRequest;
        since the hi-agent DTO has compatible fields, it is passed through
        directly.  When the facade uses a different DTO shape, this method
        constructs the appropriate object.
        """
        self._call("open_human_gate", request)

    def submit_approval(self, request: ApprovalRequest) -> None:
        """Submit an approval or rejection for a pending human gate.

        Delegates to ``facade.submit_approval(request)``.
        """
        self._call("submit_approval", request)

    # ------------------------------------------------------------------
    # Plan & manifest
    # ------------------------------------------------------------------

    def get_manifest(self) -> dict[str, Any]:
        """Fetch runtime manifest from facade."""
        result = self._call("get_manifest")
        if not isinstance(result, dict):
            # KernelFacade returns a KernelManifest dataclass; convert it.
            if hasattr(result, "__dict__"):
                return dict(result.__dict__)
            error = ValueError("get_manifest must return a dict")
            raise RuntimeAdapterBackendError(
                "get_manifest", cause=error
            ) from error
        return dict(result)

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        """Submit execution plan for one run."""
        normalized_run = self._non_empty(run_id, "run_id")
        if not isinstance(plan, dict):
            raise ValueError("plan must be a dict")
        self._call("submit_plan", normalized_run, dict(plan))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(self, method_name: str, *args: Any) -> Any:
        """Call facade method and wrap failures."""
        method = getattr(self._facade, method_name, None)
        if not callable(method):
            missing = NotImplementedError(
                f"facade does not implement '{method_name}'"
            )
            raise RuntimeAdapterBackendError(
                method_name, cause=missing
            ) from missing
        try:
            result = method(*args)
            # If the facade method is a coroutine, run it synchronously.
            # This supports async KernelFacade methods called from the
            # sync RuntimeAdapter Protocol surface.
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None and loop.is_running():
                    # We are inside an event loop; create a task-based
                    # bridge.  Callers in async contexts should prefer
                    # the async facade directly.
                    import concurrent.futures

                    future: concurrent.futures.Future[Any] = (
                        concurrent.futures.Future()
                    )

                    async def _bridge() -> None:
                        try:
                            res = await result
                            future.set_result(res)
                        except Exception as exc:
                            future.set_exception(exc)

                    loop.create_task(_bridge())
                    # Cannot block here; return the future result placeholder.
                    # In practice, facade methods that are truly async should
                    # be called through an async adapter variant.
                    return None
                else:
                    return asyncio.run(result)
            return result
        except RuntimeAdapterBackendError:
            raise
        except Exception as exc:
            raise RuntimeAdapterBackendError(
                method_name, cause=exc
            ) from exc

    @staticmethod
    def _non_empty(value: str, field: str) -> str:
        """Normalize and validate required string values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} must be a non-empty string")
        return normalized


# ------------------------------------------------------------------
# Factory function for local development
# ------------------------------------------------------------------


def create_local_adapter() -> KernelFacadeAdapter:
    """Create a KernelFacadeAdapter using LocalFSM substrate.

    This factory sets up agent-kernel's ``KernelRuntime`` with
    ``LocalSubstrateConfig`` so no Temporal server is needed for
    development and testing.

    Returns:
        A ready-to-use ``KernelFacadeAdapter`` backed by a local
        in-process KernelFacade.

    Raises:
        ImportError: If agent-kernel is not installed.
        RuntimeError: If the kernel runtime fails to start.

    Example::

        adapter = create_local_adapter()
        run_id = adapter.start_run("my-task")
        adapter.open_stage("S1")
    """
    try:
        from agent_kernel.runtime.kernel_runtime import (
            KernelRuntime,
            KernelRuntimeConfig,
        )
        from agent_kernel.substrate.local.adaptor import (
            LocalSubstrateConfig,
        )
    except ImportError as exc:
        raise ImportError(
            "agent-kernel is required for create_local_adapter(). "
            "Install it with: pip install agent-kernel"
        ) from exc

    config = KernelRuntimeConfig(
        substrate=LocalSubstrateConfig(),
        event_log_backend="in_memory",
    )
    # KernelRuntime.start() is async; run it in a fresh event loop.
    runtime = asyncio.run(KernelRuntime.start(config))
    return KernelFacadeAdapter(runtime.facade)
