"""Unit tests for routes_events.py (Arch-7 extraction).

Tests verify SSE response shape and Last-Event-ID replay path.
The event_bus module-level singleton is mocked at the boundary so
no real asyncio queues are created.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_sse_request(run_id: str = "run-1", last_event_id: str = "") -> MagicMock:
    req = MagicMock()
    req.path_params = {"run_id": run_id}
    req.headers = {"last-event-id": last_event_id} if last_event_id else {}
    req.app.state.agent_server = MagicMock()
    return req


class TestHandleRunEventsSse:
    @pytest.mark.asyncio
    async def test_returns_streaming_response(self) -> None:
        """StreamingResponse is returned with correct media type."""
        from starlette.responses import StreamingResponse
        from hi_agent.server.routes_events import handle_run_events_sse

        req = _make_sse_request()

        # Patch event_bus so subscribe returns a queue that immediately yields
        # one event then blocks forever (we cancel after collecting 1 item).
        mock_event = MagicMock()
        mock_event.run_id = "run-1"
        mock_event.event_type = "stage_complete"
        mock_event.commit_offset = 1
        mock_event.payload_json = '{"ok": true}'

        q: asyncio.Queue = asyncio.Queue()
        await q.put(mock_event)

        with patch("hi_agent.server.routes_events.event_bus") as mock_bus:
            mock_bus.subscribe.return_value = q
            mock_bus.unsubscribe = MagicMock()

            resp = await handle_run_events_sse(req)

        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_last_event_id_replay(self) -> None:
        """When Last-Event-ID is set and store has missed events, they are replayed."""
        from hi_agent.server.routes_events import handle_run_events_sse

        req = _make_sse_request(run_id="run-2", last_event_id="5")

        stored_event = MagicMock()
        stored_event.sequence = 6
        stored_event.payload_json = '{"msg": "replayed"}'

        mock_store = MagicMock()
        mock_store.list_since.return_value = [stored_event]

        q: asyncio.Queue = asyncio.Queue()
        # No more events — generator will block; we'll just consume the replay chunk.

        with patch("hi_agent.server.routes_events.event_bus") as mock_bus:
            mock_bus._event_store = mock_store
            mock_bus.subscribe.return_value = q
            mock_bus.unsubscribe = MagicMock()

            resp = await handle_run_events_sse(req)

        # Collect the first SSE chunk (the replayed event).
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
            break  # only need the first replayed chunk

        assert len(chunks) == 1
        assert "id: 6" in chunks[0]
        assert "replayed" in chunks[0]
