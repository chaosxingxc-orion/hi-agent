"""Notification helpers for observability pipelines."""

from __future__ import annotations

from copy import deepcopy
from typing import Protocol


class NotificationBackend(Protocol):
    """Minimal notification backend protocol."""

    def send(self, payload: dict[str, object]) -> None:
        """Emit one formatted payload."""


class InMemoryNotificationBackend:
    """In-memory sink used by tests and local integrations."""

    def __init__(self) -> None:
        """Initialize empty payload list."""
        self.payloads: list[dict[str, object]] = []

    def send(self, payload: dict[str, object]) -> None:
        """Persist a defensive copy to avoid caller-side mutations."""
        self.payloads.append(deepcopy(payload))


def _normalize_severity(severity: str) -> str:
    normalized = severity.strip().lower()
    if normalized in {"warn", "warning"}:
        return "warning"
    if normalized in {"info", "error"}:
        return normalized
    raise ValueError("severity must be one of: info, warning/warn, error")


def format_webhook_payload(
    *,
    event: str,
    severity: str,
    message: str,
    context: dict[str, object] | None = None,
    timestamp: float | None = None,
) -> dict[str, object]:
    """Build a normalized payload for webhook-like sinks."""
    if not event or not event.strip():
        raise ValueError("event must be non-empty")
    if not message or not message.strip():
        raise ValueError("message must be non-empty")
    payload: dict[str, object] = {
        "event": event.strip(),
        "severity": _normalize_severity(severity),
        "message": message.strip(),
        "context": deepcopy(context or {}),
    }
    if timestamp is not None:
        payload["timestamp"] = float(timestamp)
    return payload


def send_notification(
    *,
    backend: NotificationBackend,
    event: str,
    severity: str,
    message: str,
    context: dict[str, object] | None = None,
    timestamp: float | None = None,
) -> dict[str, object]:
    """Format and dispatch one notification."""
    payload = format_webhook_payload(
        event=event,
        severity=severity,
        message=message,
        context=context,
        timestamp=timestamp,
    )
    backend.send(payload)
    return payload
