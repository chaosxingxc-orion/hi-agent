"""Trace context propagation via contextvars.

Provides a ``TraceContextManager`` that maintains a W3C-compatible trace
context (trace_id, span_id, parent_span_id) in a ``contextvars.ContextVar``.
This enables automatic propagation of trace identifiers across both sync
and async call chains.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class TraceContext:
    """Identifiers propagated across nested spans."""

    trace_id: str
    span_id: str
    parent_span_id: str = ""


# Module-level ContextVar so it propagates across async boundaries.
_current_trace_ctx: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "trace_context", default=None
)


def _new_id() -> str:
    """Generate a hex UUID4 for W3C trace-context compatibility."""
    return uuid4().hex


class TraceContextManager:
    """Manage trace context via ``contextvars`` for distributed tracing.

    Usage::

        mgr = TraceContextManager()
        with mgr.span("run_execute") as ctx:
            # ctx.trace_id, ctx.span_id available
            with mgr.span("stage_execute") as child:
                # child.trace_id == ctx.trace_id
                # child.parent_span_id == ctx.span_id
                ...
    """

    def __init__(self, *, id_factory: object | None = None) -> None:
        self._id_factory = id_factory or _new_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current(self) -> TraceContext | None:
        """Return the current trace context, or ``None`` if unset."""
        return _current_trace_ctx.get()

    def clear(self) -> None:
        """Reset the current trace context to ``None``."""
        _current_trace_ctx.set(None)

    def new_trace(self) -> TraceContext:
        """Start a brand-new trace (new trace_id + root span_id).

        Sets the context var and returns the new context.
        """
        ctx = TraceContext(
            trace_id=self._id_factory(),
            span_id=self._id_factory(),
        )
        _current_trace_ctx.set(ctx)
        return ctx

    def child_span(self) -> TraceContext:
        """Create a child span under the current trace context.

        Keeps the same ``trace_id``, assigns a new ``span_id``, and sets
        ``parent_span_id`` to the current ``span_id``.

        Raises ``RuntimeError`` if no trace context is active.
        """
        parent = _current_trace_ctx.get()
        if parent is None:
            raise RuntimeError("No active trace context; call new_trace() first")
        ctx = TraceContext(
            trace_id=parent.trace_id,
            span_id=self._id_factory(),
            parent_span_id=parent.span_id,
        )
        _current_trace_ctx.set(ctx)
        return ctx

    @contextmanager
    def span(self, name: str) -> Iterator[TraceContext]:
        """Context manager that creates a child span (or root trace).

        On entry the context var is updated; on exit it is restored to
        the previous value so sibling spans do not interfere.

        ``name`` is accepted for readability / future instrumentation but
        is not stored on the lightweight ``TraceContext``.
        """
        previous = _current_trace_ctx.get()
        ctx = self.new_trace() if previous is None else self.child_span()
        try:
            yield ctx
        finally:
            _current_trace_ctx.set(previous)
