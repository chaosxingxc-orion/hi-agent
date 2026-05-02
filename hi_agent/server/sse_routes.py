"""SSE HTTP endpoints for streaming run events to external clients."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from hi_agent.server.event_bus import event_bus
from hi_agent.server.event_store import SQLiteEventStore

router = APIRouter()


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request):
    """Stream all events for a run as Server-Sent Events.

    Supports ``Last-Event-ID`` reconnection: when the header is present and the
    bus has a durable store attached, missed events are replayed before live
    streaming resumes.
    """
    last_event_id_raw = request.headers.get("last-event-id", "")
    try:
        since_sequence = int(last_event_id_raw) if last_event_id_raw else 0
    except ValueError:
        since_sequence = 0

    _store: SQLiteEventStore | None = getattr(event_bus, "_event_store", None)

    async def generate():
        # Replay missed events before subscribing to the live queue.
        if since_sequence > 0 and _store is not None:
            missed = _store.list_since(run_id, since_sequence)
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
        except asyncio.CancelledError:  # rule7-exempt: expiry_wave="Wave 29"
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
