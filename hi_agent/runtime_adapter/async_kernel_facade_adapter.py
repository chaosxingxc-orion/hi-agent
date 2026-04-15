"""Async RuntimeAdapter wrapping KernelFacadeAdapter for asyncio contexts."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter


class AsyncKernelFacadeAdapter:
    """Async wrapper around KernelFacadeAdapter.

    Provides async versions of all 17 RuntimeAdapter methods plus
    execute_turn() and subscribe_events(). Sync methods are wrapped
    with asyncio.to_thread for non-blocking execution.
    """

    def __init__(self, facade: object) -> None:
        """Initialize AsyncKernelFacadeAdapter."""
        self._sync = KernelFacadeAdapter(facade)
        self._facade = facade

    # ------------------------------------------------------------------
    # Async wrappers for sync methods
    # ------------------------------------------------------------------

    async def open_stage(self, stage_id: str) -> None:
        """Run open_stage."""
        await asyncio.to_thread(self._sync.open_stage, stage_id)

    async def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Run mark_stage_state."""
        await asyncio.to_thread(self._sync.mark_stage_state, stage_id, target)

    async def record_task_view(
        self, task_view_id: str, content: dict[str, Any]
    ) -> str:
        """Run record_task_view."""
        return await asyncio.to_thread(
            self._sync.record_task_view, task_view_id, content
        )

    async def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        """Run bind_task_view_to_decision."""
        await asyncio.to_thread(
            self._sync.bind_task_view_to_decision, task_view_id, decision_ref
        )

    async def start_run(
        self, run_id: str, session_id: str, metadata: dict
    ) -> str:
        """Start run -- adapts to facade's start_run signature."""
        method = getattr(self._facade, "start_run", None)
        if callable(method):
            if inspect.iscoroutinefunction(method):
                return await method(
                    run_id=run_id, session_id=session_id, metadata=metadata
                )
            return await asyncio.to_thread(
                method, run_id, session_id, metadata
            )
        return await asyncio.to_thread(self._sync.start_run, run_id)

    async def query_run(self, run_id: str) -> dict[str, Any]:
        """Run query_run."""
        return await asyncio.to_thread(self._sync.query_run, run_id)

    async def cancel_run(self, run_id: str, reason: str) -> None:
        """Run cancel_run."""
        await asyncio.to_thread(self._sync.cancel_run, run_id, reason)

    async def resume_run(self, run_id: str) -> None:
        """Run resume_run."""
        await asyncio.to_thread(self._sync.resume_run, run_id)

    async def signal_run(
        self,
        run_id: str,
        signal: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Run signal_run."""
        await asyncio.to_thread(
            self._sync.signal_run, run_id, signal, payload
        )

    async def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Run query_trace_runtime."""
        return await asyncio.to_thread(
            self._sync.query_trace_runtime, run_id
        )

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Run stream_run_events."""
        async for event in self._sync.stream_run_events(run_id):
            yield event

    async def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
        """Run open_branch."""
        await asyncio.to_thread(
            self._sync.open_branch, run_id, stage_id, branch_id
        )

    async def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Run mark_branch_state."""
        await asyncio.to_thread(
            self._sync.mark_branch_state,
            run_id,
            stage_id,
            branch_id,
            state,
            failure_code,
        )

    async def open_human_gate(self, request: HumanGateRequest) -> None:
        """Run open_human_gate."""
        await asyncio.to_thread(self._sync.open_human_gate, request)

    async def submit_approval(self, request: ApprovalRequest) -> None:
        """Run submit_approval."""
        await asyncio.to_thread(self._sync.submit_approval, request)

    async def get_manifest(self) -> dict[str, Any]:
        """Return manifest."""
        return await asyncio.to_thread(self._sync.get_manifest)

    async def query_run_postmortem(self, run_id: str) -> Any:
        """Async delegate for query_run_postmortem."""
        return await asyncio.to_thread(self._sync.query_run_postmortem, run_id)

    async def query_child_runs(self, parent_run_id: str) -> Any:
        """Async delegate for query_child_runs."""
        return await asyncio.to_thread(self._sync.query_child_runs, parent_run_id)

    async def resolve_escalation(
        self,
        run_id: str,
        *,
        resolution_notes: str | None = None,
        caused_by: str | None = None,
    ) -> None:
        """Async delegate for resolve_escalation."""
        await asyncio.to_thread(
            self._sync.resolve_escalation,
            run_id,
            resolution_notes=resolution_notes,
            caused_by=caused_by,
        )

    # ------------------------------------------------------------------
    # New async-native methods
    # ------------------------------------------------------------------

    async def execute_turn(
        self,
        *,
        run_id: str,
        action: Any,
        handler: Any,
        idempotency_key: str,
    ) -> Any:
        """Execute one turn through the facade."""
        return await self._sync.execute_turn(
            run_id=run_id,
            action=action,
            handler=handler,
            idempotency_key=idempotency_key,
        )

    # ------------------------------------------------------------------
    # Child run management (async versions)
    # ------------------------------------------------------------------

    def spawn_child_run(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Sync delegate for spawn_child_run."""
        return self._sync.spawn_child_run(parent_run_id, task_id, config)

    async def spawn_child_run_async(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Async version of spawn_child_run.

        Delegates to the underlying sync implementation via
        ``asyncio.to_thread`` to avoid blocking the event loop.

        Args:
            parent_run_id: The parent run identifier under which to spawn.
            task_id: The task identifier to bind to the child run.
            config: Optional dict of config overrides for the child run.

        Returns:
            The child run identifier string.
        """
        return await asyncio.to_thread(
            self._sync.spawn_child_run, parent_run_id, task_id, config
        )

    async def query_child_runs_async(
        self, parent_run_id: str
    ) -> list[dict[str, Any]]:
        """Async version of query_child_runs.

        Delegates to the underlying sync implementation via
        ``asyncio.to_thread`` to avoid blocking the event loop.

        Args:
            parent_run_id: The parent run identifier to query.

        Returns:
            A list of dicts, each representing one child run summary.
        """
        return await asyncio.to_thread(
            self._sync.query_child_runs, parent_run_id
        )

    async def subscribe_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Subscribe to events for a run."""
        method = getattr(self._facade, "subscribe_events", None)
        if callable(method):
            async for event in method(run_id):
                if isinstance(event, dict):
                    yield event
                else:
                    yield (
                        event.__dict__.copy()
                        if hasattr(event, "__dict__")
                        else {"event": str(event)}
                    )
        else:
            # Fallback: use stream_run_events
            async for event in self.stream_run_events(run_id):
                yield event
