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


class WebhookNotificationBackend:
    """HTTP webhook notification backend.

    Sends formatted payloads to a configured URL via HTTP POST.
    Failures are logged but never re-raised (best-effort delivery).
    Configure via WEBHOOK_URL environment variable or pass url directly.
    """

    def __init__(self, url: str, timeout_seconds: float = 10.0) -> None:
        """Initialize with target URL and request timeout."""
        self._url = url
        self._timeout = timeout_seconds

    def send(self, payload: dict[str, object]) -> None:
        """POST payload as JSON to the configured webhook URL."""
        import json as _json
        import logging
        import urllib.request
        _logger = logging.getLogger(__name__)
        try:
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(
                self._url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as _resp:
                pass  # fire-and-forget
        except Exception as exc:
            _logger.warning(
                "WebhookNotificationBackend.send failed url=%s error=%s",
                self._url,
                exc,
            )


def build_notification_backend(url: str | None = None) -> NotificationBackend:
    """Build notification backend from URL or WEBHOOK_URL env var."""
    import os
    resolved = url or os.environ.get("WEBHOOK_URL", "")
    if resolved:
        return WebhookNotificationBackend(resolved)
    return InMemoryNotificationBackend()


def _normalize_severity(severity: str) -> str:
    """Run _normalize_severity."""
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
