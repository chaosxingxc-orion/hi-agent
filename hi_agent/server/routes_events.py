"""Event-related HTTP route handlers.

Extracted from app.py (Arch-7 decomposition). All route paths, HTTP methods,
and response schemas are identical to the originals — this is a pure move.

Handlers:
    handle_run_events_sse      GET /runs/{run_id}/events  (SSE stream)
    handle_run_events_snapshot GET /runs/{run_id}/events/snapshot  (JSON replay)
"""

from __future__ import annotations

import asyncio
import json
import threading

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from hi_agent.server.event_bus import event_bus
from hi_agent.server.event_store import SQLiteEventStore
from hi_agent.server.tenant_context import require_tenant_context

# Rule 7: countable dropped-event alarm.
_sse_events_dropped_total: int = 0
_sse_events_dropped_lock = threading.Lock()


def _increment_dropped() -> None:
    global _sse_events_dropped_total
    with _sse_events_dropped_lock:
        _sse_events_dropped_total += 1


async def handle_run_events_sse(request: Request) -> StreamingResponse | JSONResponse:
    """Stream all events for a run as Server-Sent Events.

    Supports ``Last-Event-ID`` reconnection: when the header is present and the
    bus has a durable store attached, missed events are replayed before live
    streaming resumes.
    """
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    run_id = request.path_params["run_id"]
    server = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)

    # Parse Last-Event-ID header for replay.
    last_event_id_raw = request.headers.get("last-event-id", "")
    try:
        since_sequence = int(last_event_id_raw) if last_event_id_raw else 0
    except ValueError:
        since_sequence = 0

    # Resolve the store attached to the module-level bus (may be None).
    _store: SQLiteEventStore | None = getattr(event_bus, "_event_store", None)

    async def generate():  # type: ignore[return]  expiry_wave: Wave 30
        # Replay missed events before subscribing to the live queue.
        if since_sequence > 0 and _store is not None:
            missed = _store.list_since(
                run_id,
                since_sequence,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
            )
            for stored in missed:
                yield f"id: {stored.sequence}\ndata: {stored.payload_json}\n\n"

        q = event_bus.subscribe(run_id)
        try:
            while True:
                event = await q.get()
                data = json.dumps(
                    {
                        "run_id": event.run_id,
                        "event_type": event.event_type,
                        "commit_offset": event.commit_offset,
                        "payload": event.payload_json,
                    }
                )
                yield f"id: {event.commit_offset}\ndata: {data}\n\n"
        except asyncio.CancelledError:  # rule7-exempt: expiry_wave="Wave 30"
            pass
        finally:
            event_bus.unsubscribe(run_id, q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def handle_run_events_snapshot(request: Request) -> JSONResponse:
    """Return a JSON snapshot of past events for a run (non-SSE, queryable).

    Query parameters:
        since (int, default 0): Row offset to start from.
        limit (int, default 100): Maximum number of events to return.
    """
    try:
        ctx = require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    run_id = request.path_params["run_id"]
    server = request.app.state.agent_server
    manager = server.run_manager
    run = manager.get_run(run_id, workspace=ctx)
    if run is None:
        return JSONResponse({"error": "not_found", "run_id": run_id}, status_code=404)

    try:
        since = int(request.query_params.get("since", "0"))
    except ValueError:
        since = 0
    try:
        limit = min(int(request.query_params.get("limit", "100")), 500)
    except ValueError:
        limit = 100

    _store: SQLiteEventStore | None = getattr(event_bus, "_event_store", None)
    if _store is None:
        return JSONResponse(
            {"run_id": run_id, "events": [], "count": 0, "note": "event_store_not_configured"}
        )

    events = _store.get_events(run_id, tenant_id=ctx.tenant_id, offset=since, limit=limit)
    return JSONResponse({"run_id": run_id, "events": events, "count": len(events)})
