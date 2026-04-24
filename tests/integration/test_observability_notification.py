"""Unit tests for notification helpers."""

from __future__ import annotations

import pytest
from hi_agent.observability.notification import (
    InMemoryNotificationBackend,
    format_webhook_payload,
    send_notification,
)


def test_format_webhook_payload_is_deterministic_with_injected_clock() -> None:
    """Formatter should build predictable payload shape."""
    payload = format_webhook_payload(
        event="run.failed",
        severity="error",
        message="run failed",
        context={"run_id": "run-1"},
        timestamp=123.45,
    )
    assert payload == {
        "event": "run.failed",
        "severity": "error",
        "message": "run failed",
        "timestamp": 123.45,
        "context": {"run_id": "run-1"},
    }


def test_send_notification_writes_payload_to_backend() -> None:
    """send_notification should format and deliver one payload."""
    backend = InMemoryNotificationBackend()
    payload = send_notification(
        backend=backend,
        event="run.succeeded",
        severity="info",
        message="done",
        context={"run_id": "run-2"},
        timestamp=999.0,
    )
    assert payload["event"] == "run.succeeded"
    assert len(backend.payloads) == 1
    assert backend.payloads[0] == payload


def test_notification_backend_stores_deep_copy() -> None:
    """Stored payload should not change if caller mutates original data."""
    backend = InMemoryNotificationBackend()
    context = {"details": {"attempt": 1}}
    payload = send_notification(
        backend=backend,
        event="run.warning",
        severity="warning",
        message="slow",
        context=context,
        timestamp=7.0,
    )
    context["details"]["attempt"] = 2
    assert payload["context"]["details"]["attempt"] == 1
    assert backend.payloads[0]["context"]["details"]["attempt"] == 1


def test_notification_formatter_validates_required_fields() -> None:
    """Formatter should reject empty event and message."""
    with pytest.raises(ValueError, match="event"):
        format_webhook_payload(
            event=" ",
            severity="info",
            message="ok",
        )
    with pytest.raises(ValueError, match="message"):
        format_webhook_payload(
            event="run.info",
            severity="info",
            message=" ",
        )
