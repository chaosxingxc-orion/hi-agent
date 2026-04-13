"""Lightweight in-memory tracing primitives with pluggable export."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from time import time
from typing import Protocol, runtime_checkable
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


@runtime_checkable
class TraceExporter(Protocol):
    """Protocol for span exporters.

    Implementors receive closed :class:`SpanRecord` objects and can write them
    to any sink (file, OTLP collector, stdout, etc.).
    """

    def export(self, record: SpanRecord) -> None:
        """Export a single closed span."""
        ...

    def flush(self) -> None:
        """Flush any buffered data (called on :meth:`Tracer.flush`)."""
        ...


class JsonFileTraceExporter:
    """Append-only JSONL exporter — writes one span per line.

    This fulfils the G2 audit finding: the W3C-compatible data model was
    already in place; only the export path was missing.

    File rotation
    -------------
    A new file is created each time the exporter is instantiated.  The
    ``trace_dir`` directory is created on first use.
    """

    def __init__(self, trace_dir: str = ".hi_agent/traces") -> None:
        """Initialize JsonFileTraceExporter.

        Args:
            trace_dir: Directory where JSONL trace files are written.
        """
        self._trace_dir = Path(trace_dir)
        self._file_path: Path | None = None
        self._fh = None

    def _ensure_open(self) -> None:
        if self._fh is not None:
            return
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        # Name the file by creation time so multiple exporters don't collide.
        ts = str(int(time() * 1000))
        self._file_path = self._trace_dir / f"traces_{ts}.jsonl"
        self._fh = open(self._file_path, "a", encoding="utf-8")  # noqa: SIM115

    def export(self, record: SpanRecord) -> None:
        """Append one span as a JSON line."""
        self._ensure_open()
        line = json.dumps(asdict(record), ensure_ascii=False)
        self._fh.write(line + "\n")  # type: ignore[union-attr]

    def flush(self) -> None:
        """Flush the underlying file buffer."""
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        """Close the file handle."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class Tracer:
    """In-memory tracer with deterministic hooks for tests.

    Exporters
    ---------
    Pass a list of :class:`TraceExporter` instances to ``exporters`` to stream
    closed spans to external sinks.  Each exporter's ``export()`` is called
    immediately after a span closes, so spans appear in the sink in real time.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        now_fn: Callable[[], float] | None = None,
        exporters: list[TraceExporter] | None = None,
    ) -> None:
        """Initialize tracer with injectable ID generator and clock.

        Args:
            id_factory: Callable that returns a unique string ID.
            now_fn: Callable that returns the current time as a float.
            exporters: Optional list of :class:`TraceExporter` instances.
        """
        self._id_factory = id_factory or self._default_id_factory
        self._now_fn = now_fn or time
        self._records: list[SpanRecord] = []
        self._exporters: list[TraceExporter] = list(exporters or [])

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
            record = SpanRecord(
                name=name.strip(),
                trace_id=span_context.trace_id,
                span_id=span_context.span_id,
                parent_span_id=span_context.parent_span_id,
                start_time=start_time,
                end_time=end_time,
                duration_ms=max(0.0, (end_time - start_time) * 1000.0),
                error=error_value,
            )
            self._records.append(record)
            for exporter in self._exporters:
                try:
                    exporter.export(record)
                except Exception:
                    pass  # exporters must not crash the span

    def records(self) -> list[SpanRecord]:
        """Return records sorted by start time for deterministic parent-first reads."""
        return sorted(
            self._records,
            key=lambda record: (record.start_time, record.name, record.span_id),
        )

    def flush(self) -> None:
        """Flush all exporters' buffers."""
        for exporter in self._exporters:
            try:
                exporter.flush()
            except Exception:
                pass

    def clear(self) -> None:
        """Clear in-memory records."""
        self._records.clear()

    def add_exporter(self, exporter: TraceExporter) -> None:
        """Attach an additional exporter at runtime."""
        self._exporters.append(exporter)

    @staticmethod
    def _default_id_factory() -> str:
        """Generate random IDs for non-test usage."""
        return uuid4().hex
