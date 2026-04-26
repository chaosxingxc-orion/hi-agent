"""Structured metrics collector with thread-safe counters, gauges, and histograms.

Provides Prometheus exposition format export and JSON snapshots without any
external dependencies.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MetricDef:
    """Internal metric definition."""

    name: str
    kind: str  # "counter", "gauge", "histogram"
    help_text: str = ""


# Pre-defined metric catalogue.
_METRIC_DEFS: dict[str, _MetricDef] = {
    "runs_total": _MetricDef("runs_total", "counter", "Total runs by status."),
    "runs_active": _MetricDef("runs_active", "gauge", "Currently active runs."),
    "llm_calls_total": _MetricDef("llm_calls_total", "counter", "Total LLM calls by tier."),
    "llm_tokens_total": _MetricDef("llm_tokens_total", "counter", "Total LLM tokens by direction."),
    "llm_latency_seconds": _MetricDef(
        "llm_latency_seconds",
        "histogram",
        "LLM call latency in seconds.",
    ),
    "actions_total": _MetricDef(
        "actions_total", "counter", "Total actions by effect class and status."
    ),
    "stage_duration_seconds": _MetricDef(
        "stage_duration_seconds",
        "histogram",
        "Stage execution duration in seconds.",
    ),
    "memory_retrievals_total": _MetricDef(
        "memory_retrievals_total", "counter", "Total memory retrieval operations."
    ),
    "skill_invocations_total": _MetricDef(
        "skill_invocations_total",
        "counter",
        "Total skill invocations by skill_id and outcome.",
    ),
    "llm_cost_usd_total": _MetricDef(
        "llm_cost_usd_total",
        "counter",
        "Cumulative USD spend on LLM calls.",
    ),
    "llm_cost_per_run": _MetricDef(
        "llm_cost_per_run",
        "histogram",
        "Per-run LLM cost distribution in USD.",
    ),
    # Rule 8 / Rule 15: every outgoing LLM request increments this counter.
    # Exposed as ``hi_agent_llm_requests_total`` in /metrics output.
    # Gateway code calls record_llm_request() from hi_agent.observability.fallback.
    "hi_agent_llm_requests_total": _MetricDef(
        "hi_agent_llm_requests_total",
        "counter",
        "Total outgoing LLM requests by provider, model, and tier.",
    ),
    # Rule 14: fallback / degradation signals. Any code path that substitutes
    # a heuristic or degraded result for a primary path MUST record one of
    # these counters so Rule 15's operator-shape gate is not vacuous.
    "fallback_llm": _MetricDef(
        "fallback_llm",
        "counter",
        "LLM call fell back to a degraded path (retries exhausted, gateway missing, etc.).",
    ),
    "fallback_heuristic": _MetricDef(
        "fallback_heuristic",
        "counter",
        "A subsystem produced a heuristic result in place of a model/tool call.",
    ),
    "fallback_capability": _MetricDef(
        "fallback_capability",
        "counter",
        "A capability handler returned a heuristic/degraded result.",
    ),
    "fallback_route": _MetricDef(
        "fallback_route",
        "counter",
        "Route engine fell back to a default route (rule miss, LLM router failure).",
    ),
    # Rule 7: system-scope fallback counter for events not tied to any run.
    # Incremented when record_fallback() is called with run_id="system".
    "hi_agent_fallback_no_run_scope_total": _MetricDef(
        "hi_agent_fallback_no_run_scope_total",
        "counter",
        "Fallback events recorded with run_id='system' (no run scope).",
    ),
    # TE-1: corrupt lines encountered while loading the artifact ledger.
    "hi_agent_artifact_corrupt_line_total": _MetricDef(
        "hi_agent_artifact_corrupt_line_total",
        "counter",
        "Corrupt lines skipped while loading the artifact ledger JSONL file.",
    ),
    # W4-F / Rule 7: Retry-After header parse failure in failover chain.
    "hi_agent_retry_after_parse_total": _MetricDef(
        "hi_agent_retry_after_parse_total",
        "counter",
        "Retry-After header present but not parseable as float (Rule 7 alarm).",
    ),
    # W4-F / Rule 7: MCP subprocess stderr tail read failure.
    "hi_agent_mcp_stderr_tail_failure_total": _MetricDef(
        "hi_agent_mcp_stderr_tail_failure_total",
        "counter",
        "MCP transport get_stderr_tail() raised unexpectedly (Rule 7 alarm).",
    ),
    # TE-4: per-kind Prometheus counters required by Rule 7.
    # Incremented by record_fallback() in addition to the generic fallback_<kind>
    # counters so that /metrics exposes the canonical Rule-7 names.
    "hi_agent_llm_fallback_total": _MetricDef(
        "hi_agent_llm_fallback_total",
        "counter",
        "LLM fallback events (Rule 7 gate counter).",
    ),
    "hi_agent_heuristic_fallback_total": _MetricDef(
        "hi_agent_heuristic_fallback_total",
        "counter",
        "Heuristic fallback events (Rule 7 gate counter).",
    ),
    "hi_agent_capability_fallback_total": _MetricDef(
        "hi_agent_capability_fallback_total",
        "counter",
        "Capability fallback events (Rule 7 gate counter).",
    ),
    "hi_agent_route_fallback_total": _MetricDef(
        "hi_agent_route_fallback_total",
        "counter",
        "Route fallback events (Rule 7 gate counter).",
    ),
    # Legacy fallback taxonomy counters (kept for backward-compatibility with
    # existing record_fallback() call-sites in context/, llm/, runner_stage/).
    # These predate the four-kind taxonomy but are retained so that their
    # signals are countable instead of silently dropped.
    "fallback_expected_degradation": _MetricDef(
        "fallback_expected_degradation", "counter", "Expected degradation event."
    ),
    "fallback_unexpected_exception": _MetricDef(
        "fallback_unexpected_exception", "counter", "Unexpected exception caught and swallowed."
    ),
    "fallback_security_denied": _MetricDef(
        "fallback_security_denied", "counter", "Security policy denied an action; fallback taken."
    ),
    "fallback_dependency_unavailable": _MetricDef(
        "fallback_dependency_unavailable",
        "counter",
        "External dependency unavailable; degraded path taken.",
    ),
    "fallback_heuristic_fallback": _MetricDef(
        "fallback_heuristic_fallback", "counter", "Heuristic used in place of primary logic."
    ),
    "fallback_policy_bypass_dev": _MetricDef(
        "fallback_policy_bypass_dev",
        "counter",
        "Dev-mode policy bypass (must be zero in prod releases).",
    ),
}

# Maximum samples retained for histogram-like metrics.
_HISTOGRAM_MAX_SAMPLES = 1000


@dataclass(frozen=True)
class AlertRule:
    """Definition of a threshold-based alert rule."""

    name: str
    metric_name: str
    threshold: float
    comparator: str = "gt"  # gt, gte, lt, lte, eq
    labels: dict[str, str] | None = None
    cooldown_s: float = 60.0


@dataclass(frozen=True)
class Alert:
    """A fired alert instance."""

    rule_name: str
    metric_name: str
    current_value: float
    threshold: float
    timestamp: float
    labels: dict[str, str] = field(default_factory=dict)


def default_alert_rules() -> list[AlertRule]:
    """Return a set of sensible default alert rules."""
    return [
        AlertRule(
            name="high_error_rate",
            metric_name="runs_total",
            threshold=10.0,
            comparator="gt",
            labels={"status": "failed"},
            cooldown_s=300.0,
        ),
        AlertRule(
            name="high_latency",
            metric_name="llm_latency_seconds",
            threshold=30.0,
            comparator="gt",
            cooldown_s=300.0,
        ),
        AlertRule(
            name="budget_warning",
            metric_name="llm_cost_usd_total",
            threshold=100.0,
            comparator="gt",
            cooldown_s=600.0,
        ),
    ]


def _strict_metrics_enabled() -> bool:
    """Return True if ``HI_AGENT_STRICT_METRICS`` selects strict mode."""
    return os.environ.get("HI_AGENT_STRICT_METRICS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _report_unknown_metric(metric_name: str, op: str) -> None:
    """Log an ERROR (and optionally raise) when an unknown metric name is used.

    Rule 14 forbids silently dropping fallback/degradation signals.  Any caller
    writing to a metric name that is not registered in ``_METRIC_DEFS`` has a
    wiring bug that must be visible.  In normal mode we log loudly and return.
    In strict mode (``HI_AGENT_STRICT_METRICS=1``) we raise ``KeyError`` so
    tests can assert on the defect.
    """
    known = sorted(_METRIC_DEFS.keys())
    _logger.error(
        "MetricsCollector.%s received unknown metric name %r (known=%s). "
        "This signal is being dropped — register the metric in _METRIC_DEFS.",
        op,
        metric_name,
        known,
    )
    if _strict_metrics_enabled():
        raise KeyError(f"unknown metric: {metric_name!r}")


def _labels_key(labels: dict[str, str] | None) -> str:
    """Produce a canonical string key for a label set."""
    if not labels:
        return ""
    return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))


def _prom_labels(labels: dict[str, str] | None) -> str:
    """Format labels for Prometheus exposition text."""
    key = _labels_key(labels)
    return f"{{{key}}}" if key else ""


class MetricsCollector:
    """Thread-safe metrics collector.

    Supports three metric kinds:

    * **counter** -- monotonically increasing value per label-set.
    * **gauge** -- value that can go up and down per label-set.
    * **histogram** -- stores the last *N* observed values and computes
      percentiles on read (p50 / p95 / p99).

    All public methods are protected by a single :class:`threading.Lock`.
    """

    def __init__(
        self,
        *,
        histogram_max_samples: int = _HISTOGRAM_MAX_SAMPLES,
        auto_check_alerts: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[str, float]] = {}
        self._gauges: dict[str, dict[str, float]] = {}
        self._histograms: dict[str, dict[str, deque[float]]] = {}
        self._histogram_max = histogram_max_samples
        self._auto_check_alerts = auto_check_alerts
        self._alert_rules: dict[str, AlertRule] = {}
        self._alert_callback: Any = None
        self._alert_history: list[Alert] = []
        self._alert_last_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        metric_name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a metric observation.

        For counters, *value* is added to the current total.
        For gauges, *value* replaces the current reading.
        For histograms, *value* is appended to the sample window.

        Unknown metric names are logged at ERROR level so that mis-wired
        signals surface loudly instead of being silently dropped (Rule 14).
        Set ``HI_AGENT_STRICT_METRICS=1`` to raise ``KeyError`` instead.
        """
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
            _report_unknown_metric(metric_name, "record")
            return
        lk = _labels_key(labels)
        with self._lock:
            if defn.kind == "counter":
                bucket = self._counters.setdefault(metric_name, {})
                bucket[lk] = bucket.get(lk, 0.0) + value
            elif defn.kind == "gauge":
                bucket = self._gauges.setdefault(metric_name, {})
                bucket[lk] = value
            elif defn.kind == "histogram":
                bucket = self._histograms.setdefault(metric_name, {})
                dq = bucket.setdefault(lk, deque(maxlen=self._histogram_max))
                dq.append(value)
        if self._auto_check_alerts:
            self.check_alerts()

    def increment(
        self,
        metric_name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Convenience alias: increment a counter or gauge by *value*.

        Unknown metric names are logged at ERROR level (Rule 14: signals must
        not be silently dropped). When ``HI_AGENT_STRICT_METRICS=1`` the call
        raises ``KeyError`` so mis-wired call-sites fail loudly in tests.
        """
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
            _report_unknown_metric(metric_name, "increment")
            return
        lk = _labels_key(labels)
        with self._lock:
            if defn.kind == "counter":
                bucket = self._counters.setdefault(metric_name, {})
                bucket[lk] = bucket.get(lk, 0.0) + value
            elif defn.kind == "gauge":
                bucket = self._gauges.setdefault(metric_name, {})
                bucket[lk] = bucket.get(lk, 0.0) + value

    def gauge_set(
        self,
        metric_name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge to an absolute value."""
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
            _report_unknown_metric(metric_name, "gauge_set")
            return
        if defn.kind != "gauge":
            return
        lk = _labels_key(labels)
        with self._lock:
            bucket = self._gauges.setdefault(metric_name, {})
            bucket[lk] = value

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return all current metric values as a JSON-friendly dict."""
        with self._lock:
            result: dict[str, Any] = {}

            for name, bucket in self._counters.items():
                result[name] = self._snapshot_labeled(bucket)

            for name, bucket in self._gauges.items():
                result[name] = self._snapshot_labeled(bucket)

            for name, bucket in self._histograms.items():
                hist_out: dict[str, Any] = {}
                for lk, dq in bucket.items():
                    samples = sorted(dq)
                    entry: dict[str, Any] = {
                        "count": len(samples),
                        "sum": sum(samples),
                    }
                    if samples:
                        entry["p50"] = self._percentile(samples, 0.50)
                        entry["p95"] = self._percentile(samples, 0.95)
                        entry["p99"] = self._percentile(samples, 0.99)
                    label_key = lk if lk else "_total"
                    hist_out[label_key] = entry
                result[name] = hist_out

            return result

    def to_prometheus_text(self) -> str:
        """Return all metrics in Prometheus exposition format (text/plain)."""
        lines: list[str] = []
        with self._lock:
            # Counters
            for name, bucket in sorted(self._counters.items()):
                defn = _METRIC_DEFS.get(name)
                if defn:
                    lines.append(f"# HELP {name} {defn.help_text}")
                    lines.append(f"# TYPE {name} counter")
                for lk, val in sorted(bucket.items()):
                    prom_lbl = f"{{{lk}}}" if lk else ""
                    lines.append(f"{name}{prom_lbl} {val}")

            # Gauges
            for name, bucket in sorted(self._gauges.items()):
                defn = _METRIC_DEFS.get(name)
                if defn:
                    lines.append(f"# HELP {name} {defn.help_text}")
                    lines.append(f"# TYPE {name} gauge")
                for lk, val in sorted(bucket.items()):
                    prom_lbl = f"{{{lk}}}" if lk else ""
                    lines.append(f"{name}{prom_lbl} {val}")

            # Histograms (expose as summary-style with count/sum/quantiles)
            for name, bucket in sorted(self._histograms.items()):
                defn = _METRIC_DEFS.get(name)
                if defn:
                    lines.append(f"# HELP {name} {defn.help_text}")
                    lines.append(f"# TYPE {name} summary")
                for lk, dq in sorted(bucket.items()):
                    samples = sorted(dq)
                    prom_lbl_base = lk
                    if samples:
                        for q, tag in [
                            (0.5, "0.5"),
                            (0.95, "0.95"),
                            (0.99, "0.99"),
                        ]:
                            qlbl = (
                                f'{{quantile="{tag}",{prom_lbl_base}}}'
                                if prom_lbl_base
                                else f'{{quantile="{tag}"}}'
                            )
                            lines.append(f"{name}{qlbl} {self._percentile(samples, q)}")
                    count_lbl = f"{{{prom_lbl_base}}}" if prom_lbl_base else ""
                    lines.append(f"{name}_count{count_lbl} {len(samples)}")
                    lines.append(f"{name}_sum{count_lbl} {sum(samples)}")

        # Prometheus expects a trailing newline.
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _snapshot_labeled(bucket: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for lk, val in bucket.items():
            label_key = lk if lk else "_total"
            out[label_key] = val
        return out

    # ------------------------------------------------------------------
    # Alert subsystem
    # ------------------------------------------------------------------

    def add_alert_rule(self, rule: AlertRule) -> None:
        """Register an alert rule."""
        with self._lock:
            self._alert_rules[rule.name] = rule

    def set_alert_callback(self, callback: Any) -> None:
        """Set a callable invoked for each fired alert."""
        with self._lock:
            self._alert_callback = callback

    def check_alerts(self) -> list[Alert]:
        """Evaluate all alert rules against current metric values.

        Returns a list of :class:`Alert` instances for rules whose
        conditions are met and whose cooldown has expired.
        """
        now = time.time()
        fired: list[Alert] = []
        with self._lock:
            for rule in self._alert_rules.values():
                value = self._read_metric_value(rule.metric_name, rule.labels)
                if value is None:
                    continue
                if not self._compare(value, rule.threshold, rule.comparator):
                    continue
                last = self._alert_last_fired.get(rule.name, 0.0)
                if now - last < rule.cooldown_s:
                    continue
                alert = Alert(
                    rule_name=rule.name,
                    metric_name=rule.metric_name,
                    current_value=value,
                    threshold=rule.threshold,
                    timestamp=now,
                    labels=dict(rule.labels) if rule.labels else {},
                )
                fired.append(alert)
                self._alert_history.append(alert)
                self._alert_last_fired[rule.name] = now
                if self._alert_callback is not None:
                    self._alert_callback(alert)
        return fired

    def get_alert_history(self) -> list[Alert]:
        """Return all previously fired alerts."""
        with self._lock:
            return list(self._alert_history)

    @property
    def completed_run_count(self) -> int:
        """Return the cumulative number of completed runs recorded so far.

        Reads the ``runs_total`` counter filtered to ``status=completed``
        label entries and returns their sum as an integer.  Falls back to
        summing all ``runs_total`` label buckets when no completed-specific
        entry is present.
        """
        with self._lock:
            bucket = self._counters.get("runs_total", {})
            if not bucket:
                return 0
            # Prefer the explicit completed-status bucket.
            for lk, val in bucket.items():
                if 'status="completed"' in lk or "status=completed" in lk:
                    return int(val)
            # Fall back to total across all statuses.
            return int(sum(bucket.values()))

    # ------------------------------------------------------------------
    # Alert internals
    # ------------------------------------------------------------------

    def _read_metric_value(self, metric_name: str, labels: dict[str, str] | None) -> float | None:
        """Read a single metric value under lock (caller holds lock)."""
        lk = _labels_key(labels)
        if metric_name in self._counters:
            return self._counters[metric_name].get(lk)
        if metric_name in self._gauges:
            return self._gauges[metric_name].get(lk)
        if metric_name in self._histograms:
            dq = self._histograms[metric_name].get(lk)
            if dq:
                samples = sorted(dq)
                return self._percentile(samples, 0.95)
        return None

    @staticmethod
    def _compare(value: float, threshold: float, comparator: str) -> bool:
        if comparator == "gt":
            return value > threshold
        if comparator == "gte":
            return value >= threshold
        if comparator == "lt":
            return value < threshold
        if comparator == "lte":
            return value <= threshold
        if comparator == "eq":
            return value == threshold
        return False

    @staticmethod
    def _percentile(sorted_samples: list[float], q: float) -> float:
        """Nearest-rank percentile over a pre-sorted list."""
        n = len(sorted_samples)
        if n == 0:
            return 0.0
        rank = ceil(q * n)
        return sorted_samples[max(0, rank - 1)]


# ----------------------------------------------------------------------
# Process-level singleton
# ----------------------------------------------------------------------
#
# ``record_fallback`` needs access to a shared MetricsCollector even when
# called from deeply-nested code paths that were not given an explicit
# injection.  Callers that build their own collector should register it
# here via :func:`set_metrics_collector` so fallback signals are countable.

_SINGLETON_LOCK = threading.Lock()
_SINGLETON: MetricsCollector | None = None


def set_metrics_collector(collector: MetricsCollector | None) -> None:
    """Register a process-wide default MetricsCollector.

    Passing ``None`` clears the registration (primarily for test isolation).
    """
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = collector


def get_metrics_collector() -> MetricsCollector | None:
    """Return the process-wide MetricsCollector, or ``None`` if unset."""
    with _SINGLETON_LOCK:
        return _SINGLETON
