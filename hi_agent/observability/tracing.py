"""Lightweight in-memory tracing primitives."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import time
from uuid import uuid4


@dataclass(frozen=True)
class TraceContext:
    """Identifiers propagated across nested spans."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None


@dataclass(frozen=True)
class SpanRecord:
    """Closed span record captured by the tracer."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time: float
    end_time: float
    duration_ms: float
    error: str | None = None


class Tracer:
    """In-memory tracer with deterministic hooks for tests."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        """Initialize tracer with injectable ID generator and clock."""
        self._id_factory = id_factory or self._default_id_factory
        self._now_fn = now_fn or time
        self._records: list[SpanRecord] = []

    @contextmanager
    def span(self, name: str, parent: TraceContext | None = None) -> Iterator[TraceContext]:
        """Open and close a span around a context block."""
        if not name or not name.strip():
            raise ValueError("span name must be a non-empty string")

        start_time = float(self._now_fn())
        trace_id = parent.trace_id if parent is not None else self._id_factory()
        span_context = TraceContext(
            trace_id=trace_id,
            span_id=self._id_factory(),
            parent_span_id=parent.span_id if parent is not None else None,
        )
        error_value: str | None = None
        try:
            yield span_context
        except Exception as exc:
            error_value = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            end_time = float(self._now_fn())
            self._records.append(
                SpanRecord(
                    name=name.strip(),
                    trace_id=span_context.trace_id,
                    span_id=span_context.span_id,
                    parent_span_id=span_context.parent_span_id,
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=max(0.0, (end_time - start_time) * 1000.0),
                    error=error_value,
                )
            )

    def records(self) -> list[SpanRecord]:
        """Return records sorted by start time for deterministic parent-first reads."""
        return sorted(
            self._records,
            key=lambda record: (record.start_time, record.name, record.span_id),
        )

    def clear(self) -> None:
        """Clear in-memory records."""
        self._records.clear()

    @staticmethod
    def _default_id_factory() -> str:
        """Generate random IDs for non-test usage."""
        return uuid4().hex
