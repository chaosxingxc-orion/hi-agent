"""Event facade — cancel + event streaming (W24 Track I-A).

Per R-AS-1 this module owns the conversion from contract dataclasses to
constructor-injected callables; routes import only this facade and the
contract types. NO ``hi_agent.*`` imports here or in routes.

Per R-AS-8 facade modules must stay <=200 LOC.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from agent_server.contracts.errors import ContractError
from agent_server.contracts.run import RunStatus
from agent_server.contracts.tenancy import TenantContext

# Callable signatures — MUST raise contract errors for tenant-visible failures.
CancelRunFn = Callable[..., dict[str, Any]]
GetRunFn = Callable[..., dict[str, Any]]
IterEventsFn = Callable[..., Iterable[dict[str, Any]]]


class EventFacade:
    """Adapter for the cancel + event-stream surface.

    The ``iter_events`` callable MUST honour tenant scoping itself; per
    W24-J2's :func:`EventStore.get_events` contract the kernel side
    raises if ``tenant_id`` is missing under research/prod posture.
    """

    def __init__(
        self,
        *,
        cancel_run: CancelRunFn,
        get_run: GetRunFn,
        iter_events: IterEventsFn,
    ) -> None:
        self._cancel_run = cancel_run
        self._get_run = get_run
        self._iter_events = iter_events

    def cancel(self, ctx: TenantContext, run_id: str) -> RunStatus:
        record = self._cancel_run(tenant_id=ctx.tenant_id, run_id=run_id)
        return RunStatus(
            tenant_id=record["tenant_id"],
            run_id=record["run_id"],
            state=record["state"],
            current_stage=record.get("current_stage"),
            llm_fallback_count=int(record.get("llm_fallback_count", 0)),
            finished_at=record.get("finished_at"),
        )

    def assert_run_visible(
        self, ctx: TenantContext, run_id: str
    ) -> RunStatus:
        """Raise NotFoundError if run is not visible to ``ctx.tenant_id``."""
        record = self._get_run(tenant_id=ctx.tenant_id, run_id=run_id)
        return RunStatus(
            tenant_id=record["tenant_id"],
            run_id=record["run_id"],
            state=record["state"],
            current_stage=record.get("current_stage"),
            llm_fallback_count=int(record.get("llm_fallback_count", 0)),
            finished_at=record.get("finished_at"),
        )

    def iter_events(
        self, ctx: TenantContext, run_id: str
    ) -> Iterable[dict[str, Any]]:
        """Tenant-scoped iterator — caller is responsible for SSE framing."""
        # ``ContractError`` from the underlying callable bubbles up
        # unchanged; route code converts it to the tenant-visible status.
        return self._iter_events(tenant_id=ctx.tenant_id, run_id=run_id)


def render_sse_chunk(event: dict[str, Any]) -> str:
    """Render a single event row as an SSE frame.

    The shape mirrors hi_agent's existing SSE format:
    ``id: <sequence>\\ndata: <json>\\n\\n``.
    """
    import json as _json

    sequence = event.get("sequence", 0)
    payload = event.get("payload_json")
    if payload is None:
        payload = _json.dumps(event.get("payload", {}))
    if not isinstance(payload, str):
        payload = _json.dumps(payload)
    body = _json.dumps(
        {
            "run_id": event.get("run_id", ""),
            "event_type": event.get("event_type", ""),
            "sequence": sequence,
            "payload": payload,
        }
    )
    return f"id: {sequence}\ndata: {body}\n\n"


# Re-exported here so route handlers don't have to know it lives in
# the contracts module — keeps the facade as the only intermediary.
__all__ = ["ContractError", "EventFacade", "render_sse_chunk"]
