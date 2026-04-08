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
        self._sync = KernelFacadeAdapter(facade)
        self._facade = facade

    # ------------------------------------------------------------------
    # Async wrappers for sync methods
    # ------------------------------------------------------------------

    async def open_stage(self, stage_id: str) -> None:
        await asyncio.to_thread(self._sync.open_stage, stage_id)

    async def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        await asyncio.to_thread(self._sync.mark_stage_state, stage_id, target)

    async def record_task_view(
        self, task_view_id: str, content: dict[str, Any]
    ) -> str:
        return await asyncio.to_thread(
            self._sync.record_task_view, task_view_id, content
        )

    async def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
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
        return await asyncio.to_thread(self._sync.query_run, run_id)

    async def cancel_run(self, run_id: str, reason: str) -> None:
        await asyncio.to_thread(self._sync.cancel_run, run_id, reason)

    async def resume_run(self, run_id: str) -> None:
        await asyncio.to_thread(self._sync.resume_run, run_id)

    async def signal_run(
        self,
        run_id: str,
        signal: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._sync.signal_run, run_id, signal, payload
        )

    async def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._sync.query_trace_runtime, run_id
        )

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self._sync.stream_run_events(run_id):
            yield event

    async def open_branch(
        self, run_id: str, stage_id: str, branch_id: str
    ) -> None:
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
        await asyncio.to_thread(
            self._sync.mark_branch_state,
            run_id,
            stage_id,
            branch_id,
            state,
            failure_code,
        )

    async def open_human_gate(self, request: HumanGateRequest) -> None:
        await asyncio.to_thread(self._sync.open_human_gate, request)

    async def submit_approval(self, request: ApprovalRequest) -> None:
        await asyncio.to_thread(self._sync.submit_approval, request)

    async def get_manifest(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._sync.get_manifest)

    async def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        await asyncio.to_thread(self._sync.submit_plan, run_id, plan)

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
