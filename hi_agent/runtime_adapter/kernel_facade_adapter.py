"""RuntimeAdapter implementation backed by agent-kernel's KernelFacade.

Maps the 17-method RuntimeAdapter Protocol surface to calls on
``agent_kernel.adapters.facade.KernelFacade``. The adapter keeps a thin translation
layer: it normalises hi-agent DTO shapes into the arguments the facade
expects and wraps all errors uniformly in ``RuntimeAdapterBackendError``.

For development use without a Temporal server, see
:func:`create_local_adapter` which wires ``KernelRuntime`` with
``LocalSubstrateConfig``.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError


def _ensure_workflow_signal_run_compat(facade: object) -> None:
    """Backfill workflow gateway `signal_run` when only `signal_workflow` exists."""
    workflow_gateway = getattr(facade, "_workflow_gateway", None)
    if workflow_gateway is None or hasattr(workflow_gateway, "signal_run"):
        return
    signal_workflow = getattr(workflow_gateway, "signal_workflow", None)
    if not callable(signal_workflow):
        return

    async def _signal_run(request: Any) -> Any:
        run_id = getattr(request, "run_id", None)
        return await signal_workflow(run_id, request)

    workflow_gateway.signal_run = _signal_run


class KernelFacadeAdapter:
    """Forward RuntimeAdapter Protocol calls to an agent-kernel KernelFacade.

    Each of the 17 Protocol methods is mapped to its KernelFacade
    counterpart.  Where the facade uses typed request DTOs (e.g.
    ``StartRunRequest``), this adapter constructs them from the simpler
    positional arguments defined in the Protocol.

    Only a real ``agent_kernel.adapters.facade.KernelFacade`` instance is
    accepted.
    """

    def __init__(self, facade: object) -> None:
        """Store facade instance used for forwarding calls.

        Args:
            facade: A real ``agent_kernel.adapters.facade.KernelFacade``
                instance.
        """
        self._facade = facade
        # Tracks the active run_id after start_run(); required by open_stage
        # and mark_stage_state when the real KernelFacade needs it.
        self._current_run_id: str | None = None
        try:
            from agent_kernel.adapters.facade.kernel_facade import (
                KernelFacade as _KernelFacade,
            )
        except ImportError as exc:
            raise ImportError("agent-kernel is required for KernelFacadeAdapter.") from exc

        if not isinstance(facade, _KernelFacade):
            raise RuntimeError(
                "KernelFacadeAdapter requires a real "
                "agent_kernel.adapters.facade.KernelFacade instance."
            )

    @property
    def mode(self) -> Literal["local-fsm", "http"]:
        """The kernel execution mode — always local-fsm for KernelFacadeAdapter."""
        return "local-fsm"

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def open_stage(self, run_id: str, stage_id: str) -> None:
        """Open a stage in facade runtime."""
        normalized_run = self._non_empty(run_id, "run_id")
        normalized = self._non_empty(stage_id, "stage_id")
        self._call("open_stage", normalized, normalized_run)

    def mark_stage_state(self, run_id: str, stage_id: str, target: StageState) -> None:
        """Mark stage state in facade runtime.

        KernelFacade signature: ``mark_stage_state(run_id, stage_id, new_state)``.
        """
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_stage = self._non_empty(stage_id, "stage_id")
        normalized_target = target.value if isinstance(target, StageState) else str(target)
        self._call(
            "mark_stage_state",
            normalized_run,
            normalized_stage,
            normalized_target,
        )

    # ------------------------------------------------------------------
    # Task view
    # ------------------------------------------------------------------

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        """Record task view payload and return stored ID."""
        normalized_task_view = self._non_empty(task_view_id, "task_view_id")
        if not isinstance(content, dict):
            raise ValueError("content must be a dict")
        from agent_kernel.kernel.contracts import TaskViewRecord

        if self._current_run_id is None:
            raise RuntimeAdapterBackendError(
                "record_task_view",
                cause=ValueError("record_task_view requires run context; call start_run() first"),
            )
        result = self._call(
            "record_task_view",
            TaskViewRecord(
                task_view_id=normalized_task_view,
                run_id=self._current_run_id,
                selected_model_role=str(content.get("selected_model_role", "heavy_reasoning")),
                assembled_at=str(
                    content.get(
                        "assembled_at",
                        datetime.datetime.now(datetime.UTC).isoformat(),
                    )
                ),
                decision_ref=content.get("decision_ref"),
                stage_id=content.get("stage_id"),
                branch_id=content.get("branch_id"),
                task_contract_ref=content.get("task_contract_ref"),
                evidence_refs=list(content.get("evidence_refs", [])),
                memory_refs=list(content.get("memory_refs", [])),
                knowledge_refs=list(content.get("knowledge_refs", [])),
            ),
        )
        if isinstance(result, str) and result.strip():
            return result
        return normalized_task_view

    def bind_task_view_to_decision(self, task_view_id: str, decision_ref: str) -> None:
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

        Constructs a ``StartRunRequest`` DTO for KernelFacade and extracts
        ``run_id`` from the ``StartRunResponse``.
        """
        normalized_task = self._non_empty(task_id, "task_id")
        from agent_kernel.adapters.facade.kernel_facade import (
            StartRunRequest,
        )

        unique_run_id = f"{normalized_task[:48]}-{uuid.uuid4().hex[:8]}"
        request = StartRunRequest(
            initiator="agent_core_runner",
            run_kind="trace",
            input_json={"task_id": normalized_task, "run_id": unique_run_id},
        )
        result = self._call("start_run", request)
        if hasattr(result, "run_id"):
            run_id: str = result.run_id
            self._current_run_id = run_id
            return run_id

        if not isinstance(result, str) or not result.strip():
            error = ValueError("start_run must return a non-empty run_id string")
            raise RuntimeAdapterBackendError("start_run", cause=error) from error
        self._current_run_id = result
        return result

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Query one run snapshot."""
        normalized_run = self._non_empty(run_id, "run_id")
        from agent_kernel.adapters.facade.kernel_facade import QueryRunRequest

        result = self._call("query_run", QueryRunRequest(run_id=normalized_run))
        if isinstance(result, dict):
            return dict(result)
        import dataclasses

        if dataclasses.is_dataclass(result) and not isinstance(result, type):
            return dataclasses.asdict(result)
        error = ValueError("query_run must return a dict")
        raise RuntimeAdapterBackendError("query_run", cause=error) from error

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel one run with reason."""
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_reason = self._non_empty(reason, "reason")
        from agent_kernel.adapters.facade.kernel_facade import CancelRunRequest

        self._call("cancel_run", CancelRunRequest(run_id=normalized_run, reason=normalized_reason))

    def resume_run(self, run_id: str) -> None:
        """Resume a waiting or paused run."""
        normalized_run = self._non_empty(run_id, "run_id")
        from agent_kernel.adapters.facade.kernel_facade import ResumeRunRequest

        self._call("resume_run", ResumeRunRequest(run_id=normalized_run))

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
        from agent_kernel.adapters.facade.kernel_facade import SignalRunRequest

        self._call(
            "signal_run",
            SignalRunRequest(
                run_id=normalized_run,
                signal_type=normalized_signal,
                signal_payload=dict(normalized_payload),
            ),
        )

    # ------------------------------------------------------------------
    # Trace runtime
    # ------------------------------------------------------------------

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Query extended runtime trace payload."""
        normalized_run = self._non_empty(run_id, "run_id")
        result = self._call("query_trace_runtime", normalized_run)
        if isinstance(result, dict):
            return dict(result)
        import dataclasses

        if dataclasses.is_dataclass(result) and not isinstance(result, type):
            return dataclasses.asdict(result)
        error = ValueError("query_trace_runtime must return a dict")
        raise RuntimeAdapterBackendError("query_trace_runtime", cause=error) from error

    async def stream_run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
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
            missing = NotImplementedError("facade does not implement 'stream_run_events'")
            raise RuntimeAdapterBackendError("stream_run_events", cause=missing) from missing
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
            raise RuntimeAdapterBackendError("stream_run_events", cause=exc) from exc

    # ------------------------------------------------------------------
    # Branch lifecycle
    # ------------------------------------------------------------------

    def open_branch(self, run_id: str, stage_id: str, branch_id: str) -> None:
        """Open a branch under one stage."""
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_stage = self._non_empty(stage_id, "stage_id")
        normalized_branch = self._non_empty(branch_id, "branch_id")
        from agent_kernel.adapters.facade.kernel_facade import OpenBranchRequest

        self._call(
            "open_branch",
            OpenBranchRequest(
                run_id=normalized_run,
                branch_id=normalized_branch,
                stage_id=normalized_stage,
            ),
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
        normalized_run = self._non_empty(run_id, "run_id")
        normalized_branch = self._non_empty(branch_id, "branch_id")
        normalized_state = self._non_empty(state, "state")
        normalized_failure = (
            None if failure_code is None else self._non_empty(failure_code, "failure_code")
        )
        from agent_kernel.adapters.facade.kernel_facade import (
            BranchStateUpdateRequest,
        )
        from agent_kernel.kernel.contracts import TraceFailureCode

        failure_val = None
        reason = None
        if normalized_failure is not None:
            try:
                failure_val = TraceFailureCode(normalized_failure)
            except (ValueError, TypeError):
                reason = normalized_failure
        self._call(
            "mark_branch_state",
            BranchStateUpdateRequest(
                run_id=normalized_run,
                branch_id=normalized_branch,
                new_state=normalized_state,  # type: ignore[arg-type]  expiry_wave: Wave 30
                failure_code=failure_val,
                reason=reason,
            ),
        )

    # ------------------------------------------------------------------
    # Human gate
    # ------------------------------------------------------------------

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open a human gate and block until resolved or timed out.

        Converts hi-agent request DTO to agent-kernel ``HumanGateRequest``.
        """
        from agent_kernel.adapters.facade.kernel_facade import (
            HumanGateRequest as KernelHumanGateRequest,
        )

        from hi_agent.config.posture_guards import require_tenant

        context = dict(getattr(request, "context", {}) or {})
        # Priority: explicit field > context dict > posture guard
        _tenant = request.tenant_id or str(context.get("tenant_id") or "")
        _user = request.user_id or str(context.get("user_id") or "")
        _session = request.session_id or str(context.get("session_id") or "")
        _project = request.project_id or str(context.get("project_id") or "")
        _tenant = require_tenant(_tenant or None, where="open_human_gate")
        self._call(
            "open_human_gate",
            KernelHumanGateRequest(
                gate_ref=self._non_empty(request.gate_ref, "gate_ref"),
                gate_type=self._non_empty(request.gate_type, "gate_type"),  # type: ignore[arg-type]  expiry_wave: Wave 30
                run_id=self._non_empty(request.run_id, "run_id"),
                trigger_reason=str(
                    context.get("trigger_reason") or context.get("reason") or "human_gate_requested"
                ),
                trigger_source=str(context.get("trigger_source") or "system"),  # type: ignore[arg-type]  expiry_wave: Wave 30
                stage_id=context.get("stage_id"),
                branch_id=context.get("branch_id"),
                artifact_ref=context.get("artifact_ref"),
                caused_by=context.get("caused_by"),
                tenant_id=_tenant,
                user_id=_user,
                session_id=_session,
                project_id=_project,
            ),
        )

    def submit_approval(self, request: ApprovalRequest) -> None:
        """Submit an approval or rejection for a pending human gate.

        Converts hi-agent request DTO to agent-kernel ``ApprovalRequest``.
        """
        from agent_kernel.adapters.facade.kernel_facade import (
            ApprovalRequest as KernelApprovalRequest,
        )

        decision = self._non_empty(request.decision, "decision").lower()
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        run_id = getattr(request, "run_id", None) or self._current_run_id
        if not isinstance(run_id, str) or not run_id.strip():
            raise RuntimeAdapterBackendError(
                "submit_approval",
                cause=ValueError("submit_approval requires run context"),
            )

        self._call(
            "submit_approval",
            KernelApprovalRequest(
                run_id=run_id.strip(),
                approval_ref=self._non_empty(request.gate_ref, "gate_ref"),
                approved=(decision == "approved"),
                reviewer_id=(request.reviewer_id or "unknown_reviewer"),
                reason=(request.comment or None),
            ),
        )

    def resolve_escalation(
        self,
        run_id: str,
        *,
        resolution_notes: str | None = None,
        caused_by: str | None = None,
    ) -> None:
        """Resume a run stuck in waiting_external after human_escalation.

        ``KernelFacade.resolve_escalation`` uses keyword-only args so it
        cannot be routed through the generic ``_call()`` helper; the coroutine
        is driven inline using the same async→sync bridge.
        """
        if not isinstance(run_id, str) or not run_id.strip():
            raise RuntimeAdapterBackendError(
                "resolve_escalation",
                cause=ValueError("resolve_escalation requires a non-empty run_id"),
            )
        try:
            coro = self._facade.resolve_escalation(
                run_id.strip(),
                resolution_notes=resolution_notes,
                caused_by=caused_by,
            )
            if asyncio.iscoroutine(coro):
                # Rule 12: route through the durable SyncBridge so the facade's
                # async resources share one event loop across sync calls.
                from hi_agent.runtime.sync_bridge import get_bridge

                get_bridge().call_sync(coro)
        except RuntimeAdapterBackendError:
            raise
        except Exception as exc:
            raise RuntimeAdapterBackendError("resolve_escalation", cause=exc) from exc

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

        Requires KernelFacade ``execute_turn`` support.
        """
        method = getattr(self._facade, "execute_turn", None)
        if not callable(method):
            raise RuntimeAdapterBackendError(
                "execute_turn",
                cause=NotImplementedError("KernelFacade does not implement execute_turn"),
            )
        return await method(
            run_id=run_id,
            action=action,
            handler=handler,
            idempotency_key=idempotency_key,
        )

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
            raise RuntimeAdapterBackendError("get_manifest", cause=error) from error
        return dict(result)

    def query_run_postmortem(self, run_id: str) -> Any:
        """Delegate query_run_postmortem to kernel facade."""
        return self._call("query_run_postmortem", self._non_empty(run_id, "run_id"))

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

        Constructs a ``SpawnChildRunRequest`` DTO for KernelFacade and
        extracts ``child_run_id`` from the ``SpawnChildRunResponse``.

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
        from agent_kernel.kernel.contracts import (
            SpawnChildRunRequest,
        )

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
            ``lifecycle_state``, ``outcome``, ``created_at``, ``completed_at``,
            and ``query_error`` (non-None when kernel failed to resolve the
            child's state; callers should not treat this entry as authoritative).

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
                        import dataclasses

                        summaries.append(dataclasses.asdict(item))
                    except TypeError:
                        summaries.append({"child_run_id": str(item)})
            return summaries
        error = ValueError("query_child_runs must return a list")
        raise RuntimeAdapterBackendError("query_child_runs", cause=error) from error

    async def spawn_child_run_async(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Async version of spawn_child_run via asyncio.to_thread."""
        return await asyncio.to_thread(self.spawn_child_run, parent_run_id, task_id, config)

    async def query_child_runs_async(self, parent_run_id: str) -> list[dict[str, Any]]:
        """Async version of query_child_runs via asyncio.to_thread."""
        return await asyncio.to_thread(self.query_child_runs, parent_run_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(self, method_name: str, *args: Any) -> Any:
        """Call facade method and wrap failures."""
        method = getattr(self._facade, method_name, None)
        if not callable(method):
            missing = NotImplementedError(f"facade does not implement '{method_name}'")
            raise RuntimeAdapterBackendError(method_name, cause=missing) from missing
        try:
            result = method(*args)
            # If the facade method is a coroutine, run it synchronously.
            # This supports async KernelFacade methods called from the
            # sync RuntimeAdapter Protocol surface.
            if asyncio.iscoroutine(result):
                # Rule 12: share one durable event loop across sync calls.
                from hi_agent.runtime.sync_bridge import get_bridge

                return get_bridge().call_sync(result)
            return result
        except RuntimeAdapterBackendError:
            raise
        except Exception as exc:
            raise RuntimeAdapterBackendError(method_name, cause=exc) from exc

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

    class _InMemoryTaskViewLog:
        """Minimal in-memory TaskViewLog required by KernelFacade.record_task_view()."""

        def __init__(self) -> None:
            self._by_id: dict = {}
            self._by_decision: dict = {}

        def write(self, record: Any) -> None:
            tv_id = getattr(record, "task_view_id", None) or str(id(record))
            self._by_id[tv_id] = record

        def get_by_id(self, task_view_id: str) -> Any:
            return self._by_id.get(task_view_id)

        def get_by_decision(self, run_id: str, decision_ref: Any) -> Any:
            key = str(decision_ref)
            return self._by_decision.get(key)

        def bind_to_decision(self, task_view_id: str, decision_ref: Any) -> None:
            key = str(decision_ref)
            self._by_decision[key] = self._by_id.get(task_view_id)

    _task_view_log = _InMemoryTaskViewLog()

    # KernelRuntime.start() is async. Rule 12: run it on the process-wide
    # SyncBridge so the runtime's async resources (substrate task groups,
    # event-log connections) share one durable event loop with later facade
    # calls. This removes the need for the previous per-call daemon thread
    # + asyncio.run() dance.
    from hi_agent.runtime.sync_bridge import get_bridge

    runtime = get_bridge().call_sync(KernelRuntime.start(config))
    facade = runtime.facade
    if getattr(facade, "_task_view_log", None) is None:
        facade._task_view_log = _task_view_log
    _ensure_workflow_signal_run_compat(facade)
    return KernelFacadeAdapter(facade)
