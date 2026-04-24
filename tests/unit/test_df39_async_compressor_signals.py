"""DF-39 regression tests for async compressor fallback observability."""

from __future__ import annotations

import builtins
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hi_agent.memory.async_compressor import AsyncMemoryCompressor
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events


def _make_records() -> list[dict[str, object]]:
    return [
        {
            "event_type": "StageStateChanged",
            "payload": {"stage_id": "s1", "to_state": "running"},
        },
        {"event_type": "TaskViewRecorded", "payload": {"task_view_id": "task-1"}},
    ]


def _matching_event(run_id: str, reason: str) -> dict[str, Any]:
    events = get_fallback_events(run_id)
    assert any(event["reason"] == reason for event in events), events
    return next(event for event in events if event["reason"] == reason)


@pytest.mark.asyncio
async def test_async_compressor_gateway_none_records_fallback() -> None:
    run_id = "test-df39-async-gwnone-001"
    clear_fallback_events(run_id)

    compressor = AsyncMemoryCompressor(gateway=None)
    result = await compressor.compress(_make_records(), context="ctx", run_id=run_id)

    assert result.summary
    event = _matching_event(run_id, "gateway_unavailable")
    assert event["kind"] == "heuristic"
    assert event["extra"]["site"] == "async_compressor.compress"
    assert event["extra"]["record_count"] == 2


@pytest.mark.asyncio
async def test_async_compressor_gateway_missing_complete_records_fallback() -> None:
    run_id = "test-df39-async-missing-complete-001"
    clear_fallback_events(run_id)

    compressor = AsyncMemoryCompressor(gateway=object())
    result = await compressor.compress(_make_records(), context="ctx", run_id=run_id)

    assert result.summary
    event = _matching_event(run_id, "gateway_missing_complete")
    assert event["kind"] == "heuristic"
    assert event["extra"]["site"] == "async_compressor.compress"
    assert event["extra"]["record_count"] == 2


@pytest.mark.asyncio
async def test_async_compressor_structured_import_error_records_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "test-df39-async-struct-import-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    gateway.complete = AsyncMock(
        return_value=SimpleNamespace(
            content="plain summary",
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
        )
    )

    real_import = builtins.__import__

    def _import(name: str, globals=None, locals=None, fromlist=(), level=0):
        if name == "hi_agent.memory.structured_compression":
            raise ImportError("structured compressor unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)

    compressor = AsyncMemoryCompressor(gateway=gateway)
    result = await compressor.compress(_make_records(), context="ctx", run_id=run_id)

    assert result.summary == "plain summary"
    event = _matching_event(run_id, "structured_compressor_unavailable")
    assert event["kind"] == "heuristic"
    assert event["extra"]["site"] == "async_compressor.compress.structured_import"
    assert event["extra"]["error_type"] == "ImportError"


@pytest.mark.asyncio
async def test_async_compressor_structured_compressor_error_records_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "test-df39-async-structerr-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    gateway.complete = AsyncMock(
        return_value=SimpleNamespace(
            content="plain summary",
            usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3),
        )
    )

    from hi_agent.memory import structured_compression as structured_module

    class ExplodingStructuredCompressor:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("structured compressor blew up")

    monkeypatch.setattr(
        structured_module,
        "StructuredCompressor",
        ExplodingStructuredCompressor,
        raising=True,
    )

    compressor = AsyncMemoryCompressor(gateway=gateway)
    result = await compressor.compress(_make_records(), context="ctx", run_id=run_id)

    assert result.summary == "plain summary"
    event = _matching_event(run_id, "structured_compressor_error")
    assert event["kind"] == "llm"
    assert event["extra"]["site"] == "async_compressor.compress.structured_compress"
    assert event["extra"]["error_type"] == "RuntimeError"
