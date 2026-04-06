"""Client abstraction for forwarding runtime backend operations."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class KernelClient(Protocol):
    """Protocol for clients that send normalized operation payloads."""

    def open_stage(self, payload: dict[str, Any]) -> Any:
        """Send stage-open payload to runtime kernel."""

    def mark_stage_state(self, payload: dict[str, Any]) -> Any:
        """Send stage-state payload to runtime kernel."""

    def record_task_view(self, payload: dict[str, Any]) -> Any:
        """Send task-view payload to runtime kernel."""


class SimpleKernelClient:
    """Basic client that delegates every operation to an injected transport."""

    def __init__(self, transport: Callable[[str, dict[str, Any]], Any]) -> None:
        """Store transport callable used by all operation handlers."""
        self._transport = transport

    def open_stage(self, payload: dict[str, Any]) -> Any:
        """Send open-stage payload through transport."""
        return self._send("open_stage", payload)

    def mark_stage_state(self, payload: dict[str, Any]) -> Any:
        """Send stage-state payload through transport."""
        return self._send("mark_stage_state", payload)

    def record_task_view(self, payload: dict[str, Any]) -> Any:
        """Send task-view payload through transport."""
        return self._send("record_task_view", payload)

    def _send(self, operation: str, payload: dict[str, Any]) -> Any:
        """Execute transport call and normalize any transport error."""
        try:
            return self._transport(operation, payload)
        except Exception as exc:
            raise RuntimeError(
                f"Kernel client transport failed during '{operation}'."
            ) from exc


class HttpKernelClient:
    """HTTP client that posts normalized operation payloads as JSON."""

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float = 5.0,
        opener: Callable[..., Any] | None = None,
        auth_token: str | None = None,
        idempotency_key_factory: Callable[[str, dict[str, Any]], str | None] | None = None,
    ) -> None:
        """Initialize HTTP transport configuration.

        Args:
            endpoint: Base endpoint URL. If it ends with ``/operation`` or
                ``/operations``, a generic endpoint mode is used.
            timeout_seconds: Request timeout in seconds.
            opener: Optional opener compatible with ``urllib.request.urlopen``.
            auth_token: Optional bearer token added as Authorization header.
            idempotency_key_factory: Optional callback to generate per-request
                idempotency keys from operation and payload.
        """
        self._endpoint = endpoint.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._opener = opener or urlopen
        self._auth_token = auth_token
        self._idempotency_key_factory = idempotency_key_factory

    def open_stage(self, payload: dict[str, Any]) -> Any:
        """Send stage-open payload over HTTP."""
        return self._send("open_stage", payload)

    def mark_stage_state(self, payload: dict[str, Any]) -> Any:
        """Send stage-state payload over HTTP."""
        return self._send("mark_stage_state", payload)

    def record_task_view(self, payload: dict[str, Any]) -> Any:
        """Send task-view payload over HTTP."""
        return self._send("record_task_view", payload)

    def _send(self, operation: str, payload: dict[str, Any]) -> Any:
        """Execute HTTP request and normalize transport errors."""
        url = self._build_url(operation)
        request_payload = self._build_payload(operation, payload)
        body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url=url,
            data=body,
            headers=self._build_headers(operation, payload),
            method="POST",
        )

        try:
            response = self._opener(request, timeout=self._timeout_seconds)
            return self._parse_response(operation, response)
        except HTTPError as exc:
            raise RuntimeError(
                f"Kernel HTTP client request failed during '{operation}': HTTP {exc.code}."
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Kernel HTTP client request failed during '{operation}': network error."
            ) from exc
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Kernel HTTP client request failed during '{operation}': transport error."
            ) from exc

    def _parse_response(self, operation: str, response: Any) -> Any:
        """Parse HTTP response payload."""
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()

        if status is not None and not 200 <= int(status) < 300:
            raise RuntimeError(
                f"Kernel HTTP client request failed during '{operation}': HTTP {int(status)}."
            )

        raw_body = response.read()
        if raw_body is None or raw_body == b"":
            return None

        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Kernel HTTP client request failed during "
                f"'{operation}': invalid JSON response."
            ) from exc

    def _build_url(self, operation: str) -> str:
        """Build operation target URL."""
        if "{operation}" in self._endpoint:
            return self._endpoint.format(operation=operation)
        if self._is_generic_endpoint():
            return self._endpoint
        return f"{self._endpoint}/{operation}"

    def _build_payload(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Build request payload for operation or generic endpoint modes."""
        if self._is_generic_endpoint():
            return {"operation": operation, "payload": payload}
        return payload

    def _build_headers(self, operation: str, payload: dict[str, Any]) -> dict[str, str]:
        """Build request headers including optional auth/idempotency metadata."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._auth_token is not None:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        if self._idempotency_key_factory is not None:
            idempotency_key = self._idempotency_key_factory(operation, payload)
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
        return headers

    def _is_generic_endpoint(self) -> bool:
        """Whether endpoint is a single operation dispatcher URL."""
        return self._endpoint.endswith("/operation") or self._endpoint.endswith("/operations")
