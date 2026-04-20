"""Async KernelFacade compatibility helper backed by real agent-kernel."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from hi_agent.runtime_adapter.kernel_facade_adapter import create_local_adapter


@dataclass
class _Event:
    event_type: str
    run_id: str


class MockKernelFacade:
    """Compatibility class for AsyncTaskScheduler tests.

    Uses the real agent-kernel LocalFSM facade and maps external test run IDs
    to actual kernel run IDs.
    """

    def __init__(self) -> None:
        adapter = create_local_adapter()
        self._facade = adapter._facade
        self._run_id_map: dict[str, str] = {}
        self._events: dict[str, list[_Event]] = defaultdict(list)

    def _actual_run_id(self, run_id: str) -> str:
        return self._run_id_map.get(run_id, run_id)

    async def start_run(self, run_id: str, session_id: str, metadata: dict[str, Any]) -> None:
        from agent_kernel.adapters.facade.kernel_facade import StartRunRequest

        request = StartRunRequest(
            initiator="agent_core_runner",
            run_kind="trace",
            session_id=session_id,
            input_json={"run_id": run_id, **(metadata or {})},
        )
        response = await self._facade.start_run(request)
        self._run_id_map[run_id] = response.run_id

    async def execute_turn(
        self, run_id: str, action: Any, handler: Any, *, idempotency_key: str
    ) -> Any:
        external_run_id = run_id
        actual_run_id = self._actual_run_id(run_id)
        if actual_run_id == run_id and run_id not in self._run_id_map:
            await self.start_run(run_id, "test-session", {})
            actual_run_id = self._actual_run_id(run_id)

        result = await self._facade.execute_turn(
            run_id=actual_run_id,
            action=action,
            handler=handler,
            idempotency_key=idempotency_key,
        )
        self._events[external_run_id].append(
            _Event(event_type="turn_completed", run_id=external_run_id)
        )
        return result

    async def subscribe_events(self, run_id: str):
        # Wait briefly for locally recorded turn events (used by async tests).
        for _ in range(100):
            buffered = self._events.get(run_id, [])
            if buffered:
                for event in buffered:
                    yield event
                return
            await asyncio.sleep(0.01)
        async for event in self._facade.subscribe_events(self._actual_run_id(run_id)):
            yield event

    async def signal_run(self, run_id: str, signal: str, payload: dict[str, Any]) -> None:
        from agent_kernel.kernel.contracts import SignalRunRequest

        await self._facade.signal_run(
            SignalRunRequest(
                run_id=self._actual_run_id(run_id),
                signal_type=signal,
                signal_payload=payload,
            )
        )

    async def terminate_run(self, run_id: str, reason: str) -> None:
        from agent_kernel.kernel.contracts import CancelRunRequest

        await self._facade.cancel_run(
            CancelRunRequest(run_id=self._actual_run_id(run_id), reason=reason)
        )
