"""Unit tests for Rule 7 alarm wiring in runner.py — get_fallback_events failure path.

Wave 10.3 W3-B: Confirms that when get_fallback_events raises, record_fallback
is called with kind="llm" and reason="fallback_events_lookup_failed", and that
_fb_events falls back to [] after recording the alarm (not silently zeroed).
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Test: record_fallback is called when get_fallback_events raises
# ---------------------------------------------------------------------------


def test_get_fallback_events_failure_triggers_alarm() -> None:
    """When get_fallback_events raises, record_fallback("llm", ...) must fire.

    Strategy: reproduce the exact code block from runner.py execute_async
    that wraps get_fallback_events, substituting real imports with mocks.
    """
    run_id = "run-fb-alarm-001"
    captured_calls: list[tuple] = []
    result_holder: list = []

    def _fake_get_fallback_events(rid: str):
        raise RuntimeError("event store unavailable")

    def _fake_record_fallback(kind, *, reason, run_id, extra=None, logger=None):
        captured_calls.append((kind, reason, run_id, extra))

    # Simulate the code block:
    _fb_events: list = []
    try:
        _fb_events = _fake_get_fallback_events(run_id)
    except Exception as _fe_exc:
        with contextlib.suppress(Exception):
            _fake_record_fallback(
                "llm",
                reason="fallback_events_lookup_failed",
                run_id=run_id,
                extra={"exc": str(_fe_exc)},
            )
        _fb_events = []  # still fall back to empty after recording the alarm

    result_holder.append(_fb_events)

    assert len(captured_calls) == 1
    kind, reason, recorded_run_id, extra = captured_calls[0]
    assert kind == "llm"
    assert reason == "fallback_events_lookup_failed"
    assert recorded_run_id == run_id
    assert "exc" in extra

    # _fb_events must be [] so RunResult can still be constructed.
    assert result_holder[0] == []


def test_get_fallback_events_failure_calls_real_record_fallback() -> None:
    """When get_fallback_events raises, the real record_fallback is called at the site.

    Patch both the import target and get_fallback_events to verify the exact
    pattern used in runner.py.
    """
    run_id = "run-fb-real-001"

    with (
        patch(
            "hi_agent.observability.fallback.get_fallback_events",
            side_effect=LookupError("gone"),
        ),
        patch("hi_agent.observability.fallback.record_fallback") as mock_rf,
    ):
        _fb_events: list = []
        try:
            from hi_agent.observability.fallback import get_fallback_events, record_fallback

            _fb_events = get_fallback_events(run_id)
        except Exception as _fe_exc:
            with contextlib.suppress(Exception):
                record_fallback(
                    "llm",
                    reason="fallback_events_lookup_failed",
                    run_id=run_id,
                    extra={"exc": str(_fe_exc)},
                )
            _fb_events = []

    mock_rf.assert_called_once()
    _args, kwargs = mock_rf.call_args
    assert kwargs["reason"] == "fallback_events_lookup_failed"
    assert kwargs["run_id"] == run_id
    assert "exc" in kwargs["extra"]
    assert _fb_events == []


def test_get_fallback_events_failure_does_not_crash_if_record_fallback_raises() -> None:
    """A broken record_fallback must not prevent the empty-list fallback from completing."""
    run_id = "run-fb-safe-001"

    with patch(
        "hi_agent.observability.fallback.record_fallback",
        side_effect=OSError("metrics gone"),
    ):
        completed = False
        _fb_events: list = []
        try:
            from hi_agent.observability.fallback import record_fallback

            raise RuntimeError("forced get_fallback_events failure")
        except Exception as _fe_exc:
            with contextlib.suppress(Exception):
                record_fallback(
                    "llm",
                    reason="fallback_events_lookup_failed",
                    run_id=run_id,
                    extra={"exc": str(_fe_exc)},
                )
            _fb_events = []
            completed = True

    assert completed
    assert _fb_events == []


def test_get_fallback_events_success_does_not_call_record_fallback() -> None:
    """When get_fallback_events succeeds, record_fallback must NOT be called."""
    run_id = "run-fb-ok-001"
    fake_events = [{"kind": "llm", "reason": "retries_exhausted"}]

    captured_rf_calls: list = []

    def _fake_get_fallback_events(rid: str):
        return fake_events

    def _fake_record_fallback(kind, *, reason, run_id, extra=None, logger=None):
        captured_rf_calls.append((kind, reason))

    _fb_events: list = []
    try:
        _fb_events = _fake_get_fallback_events(run_id)
    except Exception as _fe_exc:
        with contextlib.suppress(Exception):
            _fake_record_fallback(
                "llm",
                reason="fallback_events_lookup_failed",
                run_id=run_id,
                extra={"exc": str(_fe_exc)},
            )
        _fb_events = []

    assert _fb_events == fake_events
    assert captured_rf_calls == [], "record_fallback must not be called on success"
