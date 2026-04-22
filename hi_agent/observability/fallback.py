"""Fallback taxonomy and structured recording for degradation paths.

Every code path that substitutes a heuristic or degraded result for the
primary path MUST call :func:`record_fallback` so that Rule 14 (Resilience
Must Not Mask Signals) is satisfied:

1. **Countable** — ``MetricsCollector.fallback.<kind>`` counter is incremented.
2. **Attributable** — a WARNING log line carries the ``run_id``, ``kind``,
   ``reason`` and ``extra`` context.
3. **Inspectable** — an event dict is appended to the run's
   ``fallback_events`` list, surfaced via :func:`get_fallback_events` and
   ultimately exposed on ``RunResult.fallback_events`` and
   ``GET /runs/{id}``.

Two call-shapes are supported:

* **New (preferred)** — four-kind taxonomy tied to a specific run::

      record_fallback(
          "llm",
          reason="retries_exhausted",
          run_id=run_id,
          extra={"model": "gpt-5.1"},
      )

* **Legacy** — positional ``(kind, component, detail)`` used by older
  call-sites that pre-date the four-kind taxonomy.  These recordings are
  still counted via the ``fallback.<taxonomy>`` metric and logged, but
  are not tied to a run (run_id is unknown at the call-site).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from enum import StrEnum
from typing import Any


class FallbackTaxonomy(StrEnum):
    """Structured taxonomy of fallback kinds (legacy, six-value).

    Retained so existing call-sites continue to type-check.  New code
    should use the four-kind string taxonomy documented at module level:
    ``"llm" | "heuristic" | "capability" | "route"``.
    """

    EXPECTED_DEGRADATION = "expected_degradation"
    UNEXPECTED_EXCEPTION = "unexpected_exception"
    SECURITY_DENIED = "security_denied"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    HEURISTIC_FALLBACK = "heuristic_fallback"
    POLICY_BYPASS_DEV = "policy_bypass_dev"


_logger = logging.getLogger(__name__)

# Valid kinds for the new four-kind taxonomy.  A kind outside this set is
# still recorded (not silently dropped) but logged as a defect hint so
# the fix can be traced.
_VALID_KINDS: frozenset[str] = frozenset({"llm", "heuristic", "capability", "route"})

# Process-local registry of per-run fallback events.  Populated by
# record_fallback() and drained by run finalization into RunResult.
_EVENTS_LOCK = threading.Lock()
_EVENTS: dict[str, list[dict[str, Any]]] = {}


def _coerce_kind(kind: Any) -> str:
    """Normalize a kind value to its string form."""
    if isinstance(kind, FallbackTaxonomy):
        return kind.value
    return str(kind)


def append_fallback_event(run_id: str, event: dict[str, Any]) -> None:
    """Append a fallback event to the run's event list.

    Thread-safe.  Callers are expected to pass event dicts with the shape
    ``{"kind", "reason", "ts", "extra"}``.
    """
    if not run_id:
        return
    with _EVENTS_LOCK:
        _EVENTS.setdefault(run_id, []).append(dict(event))


def get_fallback_events(run_id: str) -> list[dict[str, Any]]:
    """Return a **copy** of the fallback events recorded for ``run_id``."""
    with _EVENTS_LOCK:
        return [dict(e) for e in _EVENTS.get(run_id, [])]


def clear_fallback_events(run_id: str) -> None:
    """Drop all recorded fallback events for ``run_id`` (test isolation)."""
    with _EVENTS_LOCK:
        _EVENTS.pop(run_id, None)


def record_fallback(
    kind: Any,
    component: str | None = None,
    detail: str = "",
    *,
    reason: str | None = None,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Record a fallback event.

    Two call shapes are accepted:

    New form (Rule 14 canonical)::

        record_fallback(
            "llm",               # one of "llm" | "heuristic" | "capability" | "route"
            reason="retries_exhausted",
            run_id=run_id,
            extra={"model": "gpt-5.1"},
        )

    Legacy form (pre-existing call-sites)::

        record_fallback(FallbackTaxonomy.UNEXPECTED_EXCEPTION, "http_llm_gateway",
                        "all_retries_exhausted")

    The function never raises.  Metric increments and log emissions are
    best-effort so a mis-wired observability stack cannot crash the
    critical path.
    """

    _log = logger or _logger
    kind_str = _coerce_kind(kind)

    # Build a structured event dict regardless of call-shape.
    event: dict[str, Any] = {
        "kind": kind_str,
        "reason": reason if reason is not None else detail or "",
        "ts": time.time(),
        "extra": dict(extra) if extra else {},
    }
    if component is not None:
        event["extra"].setdefault("component", component)

    # --- 1. Increment the fallback.<kind> counter. ---
    try:
        from hi_agent.observability.collector import MetricsCollector

        # Access the process-level singleton if one has been set.
        _mc: MetricsCollector | None = getattr(MetricsCollector, "_singleton", None)
        if _mc is not None:
            labels: dict[str, str] = {}
            if reason is not None:
                labels["reason"] = reason
            if component is not None:
                labels["component"] = component
            _mc.increment(f"fallback.{kind_str}", labels=labels or None)
    except Exception:  # pragma: no cover — metrics must never crash callers
        pass

    # --- 2. Emit a WARNING log carrying run_id / kind / reason / extra. ---
    try:
        if run_id is not None or reason is not None:
            _log.warning(
                "fallback recorded run_id=%s kind=%s reason=%s extra=%s",
                run_id,
                kind_str,
                event["reason"],
                event["extra"],
            )
        else:
            # Legacy shape: preserve the previous INFO-level signal so
            # existing log-scraping rules are not disturbed, but also
            # emit a WARNING so the operator-shape gate can see it.
            _log.warning(
                "fallback recorded (legacy) kind=%s component=%s detail=%s",
                kind_str,
                component,
                detail,
            )
    except Exception:  # pragma: no cover
        pass

    # --- 3. Append to the run's fallback_events list (if run_id known). ---
    if run_id:
        with contextlib.suppress(Exception):  # pragma: no cover
            append_fallback_event(run_id, event)

    # Hint when a caller uses a kind outside the four-kind taxonomy.  This
    # is not an error (legacy taxonomy is still valid) but the hint helps
    # reviewers spot call-sites that should migrate.
    if kind_str not in _VALID_KINDS and run_id is not None:
        _log.debug(
            "record_fallback: kind=%r not in canonical four-kind set; consider migrating.",
            kind_str,
        )
