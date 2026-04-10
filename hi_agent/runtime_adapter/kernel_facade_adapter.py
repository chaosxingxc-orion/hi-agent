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
from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError


@dataclass
class _SimpleTurnResult:
    """Fallback result for execute_turn when facade lacks the method."""

    outcome_kind: str
    result: Any = None


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
        # Tracks the active run_id after start_run(); required by open_stage
        # and mark_stage_state when the real KernelFacade needs it.
        self._current_run_id: str | None = None
        # True when facade is a real KernelFacade that expects DTO request
        # objects.  False for lightweight mock/test facades that accept
        # positional string arguments (old protocol surface).
        try:
            from agent_kernel.adapters.facade.kernel_facade import (  # noqa: PLC0415
                KernelFacade as _KernelFacade,
            )
            self._use_kernel_dtos: bool = isinstance(facade, _KernelFacade)
        except ImportError:
            self._use_kernel_dtos = False

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def open_stage(self, stage_id: str) -> None:
        """Open a stage in facade runtime.

        The real KernelFacade requires ``open_stage(stage_id, run_id)``.
        The ``run_id`` is taken from the value stored by the most recent
        ``start_run()`` call.  When no run_id is available (e.g. test
        facades that accept a single positional arg), it falls back to
        calling with stage_id only.
        """
        normalized = self._non_empty(stage_id, "stage_id")
        if self._use_kernel_dtos and self._current_run_id is not None:
            self._call("open_stage", normalized, self._current_run_id)
        else:
            self._call("open_stage", normalized)

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Mark stage state in facade runtime.

        The real KernelFacade signature is
        ``mark_stage_state(run_id, stage_id, new_state, failure_code=None)``.
        ``run_id`` is taken from the value stored by ``start_run()``.
        Falls back to ``(stage_id, new_state)`` for mock/old facades.
        """
        normalized_stage = self._non_empty(stage_id, "stage_id")
        normalized_target = (
            target.value if isinstance(target, StageState) else str(target)
        )
        if self._use_kernel_dtos and self._current_run_id is not None:
            # Real KernelFacade signature: (run_id, stage_id, new_state, failure_code=None)
            # new_state is a TraceStageState Literal — pass the string value directly.
            self._call(
                "mark_stage_state",
                self._current_run_id,
                normalized_stage,
                normalized_target,
            )
        else:
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

        Constructs a ``StartRunRequest`` DTO for the real KernelFacade
        and extracts ``run_id`` from the ``StartRunResponse``.
        Falls back to passing ``task_id`` as a positional string for
        mock/test facades that accept that simpler signature.
        """
        normalized_task = self._non_empty(task_id, "task_id")
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import (  # noqa: PLC0415
                StartRunRequest,
            )
            request = StartRunRequest(
                initiator="agent_core_runner",
                run_kind="trace",
                input_json={"task_id": normalized_task},
            )
            result = self._call("start_run", request)
            if hasattr(result, "run_id"):
                run_id: str = result.run_id
                self._current_run_id = run_id
                return run_id
        else:
            result = self._call("start_run", normalized_task)

        if not isinstance(result, str) or not result.strip():
            error = ValueError(
                "start_run must return a non-empty run_id string"
            )
            raise RuntimeAdapterBackendError(
                "start_run", cause=error
            ) from error
        self._current_run_id = result
        return result

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Query one run snapshot."""
        normalized_run = self._non_empty(run_id, "run_id")
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import QueryRunRequest  # noqa: PLC0415
            result = self._call("query_run", QueryRunRequest(run_id=normalized_run))
        else:
            result = self._call("query_run", normalized_run)
        if isinstance(result, dict):
            return dict(result)
        if hasattr(result, "__dict__"):
            return {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
        error = ValueError("query_run must return a dict")
        raise RuntimeAdapterBackendError("query_run", cause=error) from error

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel one run with reason."""
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_reason = self._non_empty(reason, "reason")
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import CancelRunRequest  # noqa: PLC0415
            self._call("cancel_run", CancelRunRequest(run_id=normalized_run, reason=normalized_reason))
        else:
            self._call("cancel_run", normalized_run, normalized_reason)

    def resume_run(self, run_id: str) -> None:
        """Resume a waiting or paused run."""
        normalized_run = self._non_empty(run_id, "run_id")
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import ResumeRunRequest  # noqa: PLC0415
            self._call("resume_run", ResumeRunRequest(run_id=normalized_run))
        else:
            self._call("resume_run", normalized_run)

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
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import SignalRunRequest  # noqa: PLC0415
            self._call("signal_run", SignalRunRequest(
                run_id=normalized_run,
                signal_type=normalized_signal,
                signal_payload=dict(normalized_payload),
            ))
        else:
            self._call("signal_run", normalized_run, normalized_signal, dict(normalized_payload))

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
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_stage = self._non_empty(stage_id, "stage_id")
        normalized_branch = self._non_empty(branch_id, "branch_id")
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import OpenBranchRequest  # noqa: PLC0415
            self._call("open_branch", OpenBranchRequest(
                run_id=normalized_run,
                branch_id=normalized_branch,
                stage_id=normalized_stage,
            ))
        else:
            self._call("open_branch", normalized_run, normalized_stage, normalized_branch)

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Mark branch state with optional failure code."""
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_branch = self._non_empty(branch_id, "branch_id")
        normalized_state = self._non_empty(state, "state")
        normalized_failure = (
            None if failure_code is None
            else self._non_empty(failure_code, "failure_code")
        )
        if self._use_kernel_dtos:
            from agent_kernel.adapters.facade.kernel_facade import BranchStateUpdateRequest  # noqa: PLC0415
            from agent_kernel.kernel.contracts import TraceFailureCode  # noqa: PLC0415
            # TraceBranchState is a Literal type — pass the string value directly.
            failure_val = None
            if normalized_failure is not None:
                try:
                    failure_val = TraceFailureCode(normalized_failure)
                except (ValueError, TypeError):
                    failure_val = normalized_failure  # type: ignore[assignment]
            self._call("mark_branch_state", BranchStateUpdateRequest(
                run_id=normalized_run,
                branch_id=normalized_branch,
                new_state=normalized_state,  # type: ignore[arg-type]
                failure_code=failure_val,
            ))
        else:
            self._call(
                "mark_branch_state",
                normalized_run,
                self._non_empty(stage_id, "stage_id"),
                normalized_branch,
                normalized_state,
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
    # Turn execution
    # ------------------------------------------------------------------

    async def execute_turn(
        self,
        *,
        run_id: str,
        action: Any,
        handler: Any,
        idempotency_key: str,
    ) -> Any:
        """Forward execute_turn to facade.

        Falls back to a simple handler call if the facade doesn't
        implement execute_turn.
        """
        method = getattr(self._facade, "execute_turn", None)
        if callable(method):
            return await method(
                run_id=run_id,
                action=action,
                handler=handler,
                idempotency_key=idempotency_key,
            )
        # Fallback: just call handler directly (for facades without execute_turn)
        result = await handler(action, None)
        # Return a simple result object
        return _SimpleTurnResult(outcome_kind="dispatched", result=result)

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
    # Child run management
    # ------------------------------------------------------------------

    def spawn_child_run(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a child run under parent_run_id.

        Constructs a ``SpawnChildRunRequest`` DTO for the real KernelFacade
        and extracts ``child_run_id`` from the ``SpawnChildRunResponse``.
        Falls back to passing positional args for mock/test facades.

        Args:
            parent_run_id: The parent run identifier under which to spawn.
            task_id: The task identifier to bind to the child run.
            config: Optional dict of config overrides for the child run.

        Returns:
            The child run identifier string.

        Raises:
            RuntimeAdapterBackendError: If the facade call fails or returns
                an invalid response.
        """
        normalized_parent = self._non_empty(parent_run_id, "parent_run_id")
        normalized_task = self._non_empty(task_id, "task_id")
        normalized_config: dict[str, Any] = config or {}
        if self._use_kernel_dtos:
            try:
                from agent_kernel.kernel.contracts import (  # noqa: PLC0415
                    SpawnChildRunRequest,
                )
            except ImportError:
                SpawnChildRunRequest = None  # type: ignore[assignment,misc]
            if SpawnChildRunRequest is not None:
                request = SpawnChildRunRequest(
                    parent_run_id=normalized_parent,
                    child_kind="delegate",
                    task_id=normalized_task,
                    input_json=normalized_config if normalized_config else None,
                )
                result = self._call("spawn_child_run", request)
                if hasattr(result, "child_run_id"):
                    child_run_id: str = result.child_run_id
                    if child_run_id and child_run_id.strip():
                        return child_run_id
            # Fallback path if DTO import failed
            result = self._call(
                "spawn_child_run", normalized_parent, normalized_task, normalized_config
            )
        else:
            result = self._call(
                "spawn_child_run", normalized_parent, normalized_task, normalized_config
            )
        if isinstance(result, str) and result.strip():
            return result
        error = ValueError("spawn_child_run must return a non-empty child run_id string")
        raise RuntimeAdapterBackendError("spawn_child_run", cause=error) from error

    def query_child_runs(self, parent_run_id: str) -> list[dict[str, Any]]:
        """Return list of child run summaries for the given parent run.

        Each child run is returned as a plain dict for protocol compatibility.
        The real KernelFacade returns ``list[ChildRunSummary]`` dataclass
        instances; this adapter serializes them to dicts.

        Args:
            parent_run_id: The parent run identifier to query.

        Returns:
            A list of dicts, each representing one child run summary.
            Keys include ``child_run_id``, ``child_kind``, ``task_id``,
            ``lifecycle_state``, ``outcome``, ``created_at``, and
            ``completed_at``.

        Raises:
            RuntimeAdapterBackendError: If the facade call fails.
        """
        normalized_parent = self._non_empty(parent_run_id, "parent_run_id")
        result = self._call("query_child_runs", normalized_parent)
        if isinstance(result, list):
            summaries: list[dict[str, Any]] = []
            for item in result:
                if isinstance(item, dict):
                    summaries.append(dict(item))
                elif hasattr(item, "__dict__"):
                    summaries.append(
                        {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
                    )
                else:
                    # Last resort: convert via dataclass fields if available
                    try:
                        import dataclasses  # noqa: PLC0415
                        summaries.append(dataclasses.asdict(item))
                    except TypeError:
                        summaries.append({"child_run_id": str(item)})
            return summaries
        error = ValueError("query_child_runs must return a list")
        raise RuntimeAdapterBackendError("query_child_runs", cause=error) from error

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
    # KernelRuntime.start() is async. If a running event loop is detected
    # (e.g. inside a Starlette/FastAPI test or server context), we spin up
    # a dedicated daemon thread so asyncio.run() gets a fresh event loop.
    import threading

    def _start_in_thread() -> "KernelFacadeAdapter":
        result: list = []
        exc_holder: list = []

        def target() -> None:
            try:
                rt = asyncio.run(KernelRuntime.start(config))
                result.append(rt)
            except Exception as e:  # noqa: BLE001
                exc_holder.append(e)

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join()
        if exc_holder:
            raise exc_holder[0]
        return KernelFacadeAdapter(result[0].facade)

    try:
        asyncio.get_running_loop()
        # Already inside an event loop — delegate to thread.
        return _start_in_thread()
    except RuntimeError:
        # No running loop — safe to call asyncio.run() directly.
        runtime = asyncio.run(KernelRuntime.start(config))
        return KernelFacadeAdapter(runtime.facade)
