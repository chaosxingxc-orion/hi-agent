"""SSE HTTP endpoints for streaming run events to external clients."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from hi_agent.server.event_bus import event_bus

router = APIRouter()


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str):
    """Stream all events for a run as Server-Sent Events."""

    async def generate():
        q = event_bus.subscribe(run_id)
        try:
            while True:
                event = await q.get()
                data = json.dumps({
                    "run_id": event.run_id,
                    "event_type": event.event_type,
                    "commit_offset": event.commit_offset,
                    "payload": event.payload_json,
                })
                yield f"id: {event.commit_offset}\ndata: {data}\n\n"
        except asyncio.CancelledError:
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
