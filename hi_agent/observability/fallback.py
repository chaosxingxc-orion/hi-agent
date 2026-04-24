"""Fallback taxonomy and structured recording for degradation paths.

Every code path that substitutes a heuristic or degraded result for the
primary path MUST call :func:`record_fallback` so that Rule 7 (Resilience
Must Not Mask Signals) is satisfied:

1. **Countable** — ``MetricsCollector.fallback.<kind>`` counter is incremented.
2. **Attributable** — a WARNING log line carries the ``run_id``, ``kind``,
   ``reason`` and ``extra`` context.
3. **Inspectable** — an event dict is appended to the run's
   ``fallback_events`` list, surfaced via :func:`get_fallback_events` and
   ultimately exposed on ``RunResult.fallback_events`` and
   ``GET /runs/{id}``.

Call-shape — four-kind taxonomy tied to a specific run::

    record_fallback(
        "llm",
        reason="retries_exhausted",
        run_id=run_id,
        extra={"model": "gpt-5.1"},
    )

``run_id`` and ``reason`` are required keyword-only arguments.  Use
``run_id="system"`` for module/startup-level events not tied to a run;
use ``run_id="unknown"`` when the run context is genuinely unavailable
(add ``# TODO: wire real run_id here`` when doing so).
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


def _increment_no_run_scope_counter() -> None:
    """Increment the system-scope fallback counter (run_id == "system")."""
    try:
        from hi_agent.observability.collector import get_metrics_collector

        collector = get_metrics_collector()
        if collector is not None:
            collector.increment("hi_agent_fallback_no_run_scope_total")
    except Exception:  # pragma: no cover — metrics must never crash callers
        pass


def append_fallback_event(run_id: str, event: dict[str, Any]) -> None:
    """Append a fallback event to the run's event list.

    Thread-safe.  Callers are expected to pass event dicts with the shape
    ``{"kind", "reason", "ts", "extra"}``.
    """
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
    kind: str,
    *,
    reason: str,
    run_id: str,
    extra: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Record a fallback event.

    ``kind``, ``reason``, and ``run_id`` are required.  ``extra`` and
    ``logger`` are optional.  Use ``run_id="system"`` for module/startup
    events not tied to a specific run; use ``run_id="unknown"`` when the
    run context is genuinely unavailable.

    The function never raises.  Metric increments and log emissions are
    best-effort so a mis-wired observability stack cannot crash the
    critical path.

    Example::

        record_fallback(
            "llm",               # one of "llm" | "heuristic" | "capability" | "route"
            reason="retries_exhausted",
            run_id=run_id,
            extra={"model": "gpt-5.1"},
        )
    """

    _log = logger or _logger
    kind_str = _coerce_kind(kind)

    # Build a structured event dict.
    event: dict[str, Any] = {
        "kind": kind_str,
        "reason": reason,
        "ts": time.time(),
        "extra": dict(extra) if extra else {},
    }

    # --- 1. Increment fallback_<kind> counter. ---
    try:
        from hi_agent.observability.collector import get_metrics_collector

        collector = get_metrics_collector()
        if collector is not None:
            labels: dict[str, str] = {"reason": reason}
            if extra:
                # Expose commonly-queried labels directly on the metric.
                for lbl in ("model", "capability"):
                    val = extra.get(lbl)
                    if val is not None:
                        labels[lbl] = str(val)
            collector.increment(f"fallback_{kind_str}", labels=labels or None)
    except Exception:  # pragma: no cover — metrics must never crash callers
        pass

    # --- 2. Emit a WARNING log carrying run_id / kind / reason / extra. ---
    with contextlib.suppress(Exception):  # pragma: no cover — logging must not crash callers
        _log.warning(
            "fallback recorded run_id=%s kind=%s reason=%s extra=%s",
            run_id,
            kind_str,
            reason,
            event["extra"],
        )

    # --- 3. Append to the run's fallback_events list. ---
    # system-scope events are not tied to a run; count them separately.
    if run_id == "system":
        _increment_no_run_scope_counter()
    else:
        with contextlib.suppress(Exception):  # pragma: no cover
            append_fallback_event(run_id, event)

    # Hint when a caller uses a kind outside the four-kind taxonomy.
    if kind_str not in _VALID_KINDS:
        _log.debug(
            "record_fallback: kind=%r not in canonical four-kind set; consider migrating.",
            kind_str,
        )


def record_llm_request(
    *,
    provider: str,
    model: str,
    tier: str | None = None,
    run_id: str | None = None,
) -> None:
    """Rule-8 step 3: increment ``hi_agent_llm_requests_total`` on every outgoing LLM request.

    This function is the **only** hook gateway code should call to satisfy
    Rule 15's assertion that ``hi_agent_llm_requests_total`` increments per
    run.  It never raises — telemetry must not crash the critical path.

    Args:
        provider: LLM provider identifier (e.g. ``"openai"``, ``"anthropic"``).
        model: Model name/id (e.g. ``"gpt-4o"``, ``"claude-3-5-sonnet"``).
        tier: Optional routing tier label (e.g. ``"s-tier"``, ``"m-tier"``).
        run_id: Optional run identifier for DEBUG-level attribution.
    """
    try:
        from hi_agent.observability.collector import get_metrics_collector

        collector = get_metrics_collector()
        if collector is not None:
            labels: dict[str, str] = {"provider": provider, "model": model}
            if tier is not None:
                labels["tier"] = tier
            collector.increment("hi_agent_llm_requests_total", labels=labels)
    except Exception:  # pragma: no cover — metrics must never crash callers
        pass

    # DEBUG only — per-request INFO logs are too noisy in production.
    _logger.debug(
        "llm_request run_id=%s provider=%s model=%s tier=%s",
        run_id,
        provider,
        model,
        tier,
    )
