"""Mock KernelFacade for local development without agent-kernel running."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import sys
import pathlib
_ak = pathlib.Path(__file__).parent.parent.parent.parent / "agent-kernel"
if _ak.exists() and str(_ak) not in sys.path:
    sys.path.insert(0, str(_ak))

from agent_kernel.kernel.contracts import Action, RuntimeEvent
from agent_kernel.kernel.turn_engine import TurnResult

AsyncActionHandler = Callable[[Action, str | None], Awaitable[Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockKernelFacade:
    """In-process KernelFacade for testing and local development.

    Executes handlers directly, records events in-memory, and supports
    asyncio.Queue-based event subscription.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[RuntimeEvent]] = defaultdict(list)
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._dedupe: dict[str, TurnResult] = {}
        self._offset: dict[str, int] = defaultdict(int)

    async def start_run(self, run_id: str, session_id: str, metadata: dict) -> None:
        # Ensure keys exist
        _ = self._events[run_id]
        _ = self._subscribers[run_id]

    async def execute_turn(
        self,
        run_id: str,
        action: Action,
        handler: AsyncActionHandler,
        *,
        idempotency_key: str,
    ) -> TurnResult:
        # Dedupe: return cached result if already executed
        if idempotency_key in self._dedupe:
            return self._dedupe[idempotency_key]

        # Execute handler
        import inspect
        if inspect.iscoroutinefunction(handler):
            output = await handler(action, None)
        else:
            output = handler(action, None)

        # Build TurnResult
        self._offset[run_id] += 1
        result = TurnResult(
            state="effect_recorded",
            outcome_kind="dispatched",
            decision_ref=idempotency_key,
            decision_fingerprint=idempotency_key,
            action_commit={"output": output},
        )
        self._dedupe[idempotency_key] = result

        # Append event and notify subscribers
        event = RuntimeEvent(
            run_id=run_id,
            event_id=f"{run_id}:{idempotency_key}",
            commit_offset=self._offset[run_id],
            event_type="turn_completed",
            event_class="fact",
            event_authority="authoritative_fact",
            ordering_key=idempotency_key,
            wake_policy="projection_only",
            created_at=_now(),
            idempotency_key=idempotency_key,
            payload_json={"outcome_kind": result.outcome_kind},
        )
        self._events[run_id].append(event)
        for q in self._subscribers[run_id]:
            q.put_nowait(event)

        return result

    async def signal_run(self, run_id: str, signal: str, payload: dict) -> None:
        pass

    async def terminate_run(self, run_id: str, reason: str) -> None:
        pass

    async def subscribe_events(self, run_id: str) -> AsyncIterator[RuntimeEvent]:
        q: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._subscribers[run_id].append(q)
        try:
            # Replay existing events first
            for event in list(self._events[run_id]):
                yield event
            # Then stream new ones
            while True:
                event = await q.get()
                yield event
        finally:
            subs = self._subscribers.get(run_id, [])
            if q in subs:
                subs.remove(q)
