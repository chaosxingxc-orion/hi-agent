"""Regression tests for the 04-21 prod-mode stuck-run incident.

Covers:
- P1-5: RunManager.current_stage updates on both ``stage_start`` (StageOrchestrator)
  and ``StageStateChanged`` with ``to_state=="active"`` (runner_stage direct emission).
- P1-7: AsyncHTTPGateway.complete() does not block forever when the inner async
  call hangs; a bounded wall-clock timeout raises TimeoutError in reasonable time.
"""

from __future__ import annotations

import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from types import SimpleNamespace

import pytest
from hi_agent.server.run_manager import ManagedRun, RunManager


def _seed_run(rm: RunManager, run_id: str = "r1") -> ManagedRun:
    run = ManagedRun(run_id=run_id, task_contract={}, created_at="t", updated_at="t")
    rm._runs[run_id] = run
    return run


def test_stage_start_with_stage_name_updates_current_stage() -> None:
    rm = RunManager()
    run = _seed_run(rm)
    event = SimpleNamespace(
        event_type="stage_start", run_id="r1", payload_json={"stage_name": "perception"}
    )
    rm._on_stage_event(event)
    assert run.current_stage == "perception"


def test_stage_state_changed_to_active_updates_current_stage() -> None:
    """P1-5: runner_stage emits StageStateChanged directly; must also trigger update."""
    rm = RunManager()
    run = _seed_run(rm)
    event = SimpleNamespace(
        event_type="StageStateChanged",
        run_id="r1",
        payload_json={"stage_id": "control", "to_state": "active"},
    )
    rm._on_stage_event(event)
    assert run.current_stage == "control"


def test_stage_state_changed_non_active_does_not_update() -> None:
    rm = RunManager()
    run = _seed_run(rm)
    run.current_stage = "control"
    event = SimpleNamespace(
        event_type="StageStateChanged",
        run_id="r1",
        payload_json={"stage_id": "ignored", "to_state": "completed"},
    )
    rm._on_stage_event(event)
    assert run.current_stage == "control"


def test_stage_event_with_string_payload_still_parses() -> None:
    rm = RunManager()
    run = _seed_run(rm)
    event = SimpleNamespace(
        event_type="stage_start",
        run_id="r1",
        payload_json='{"stage_name": "execution"}',
    )
    rm._on_stage_event(event)
    assert run.current_stage == "execution"


def test_unrelated_event_type_is_ignored() -> None:
    rm = RunManager()
    run = _seed_run(rm)
    event = SimpleNamespace(event_type="RunStarted", run_id="r1", payload_json={"stage_name": "x"})
    rm._on_stage_event(event)
    assert run.current_stage is None


def test_async_http_gateway_bridge_has_bounded_timeout(monkeypatch) -> None:
    """P1-7: sync complete() must not hang indefinitely when inner coroutine stalls."""
    from hi_agent.llm.async_http_gateway import AsyncHTTPGateway
    from hi_agent.llm.protocol import LLMRequest

    gw = AsyncHTTPGateway(timeout_seconds=1, max_retries=0)

    async def _hang(_req):
        import asyncio

        await asyncio.sleep(60)
        raise AssertionError("should have been cancelled by timeout")

    gw._inner.complete = _hang  # type: ignore[method-assign]  expiry_wave: Wave 27

    # Drive from inside a running event loop so the bridge path is taken.
    import asyncio

    async def _driver():
        return gw.complete(LLMRequest(model="default", messages=[{"role": "user", "content": "x"}]))

    start = time.monotonic()
    with pytest.raises((FuturesTimeoutError, TimeoutError)):
        asyncio.run(_driver())
    elapsed = time.monotonic() - start
    # Bridge timeout = inner_timeout(1) * (retries+1=1) + 10 = 11s; allow 20s ceiling.
    assert elapsed < 20, f"bridge waited {elapsed:.1f}s — timeout guard not effective"
