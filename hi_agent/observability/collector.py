"""Structured metrics collector with thread-safe counters, gauges, and histograms.

Provides Prometheus exposition format export and JSON snapshots without any
external dependencies.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from typing import Any


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

        Unknown metric names are silently ignored so that callers can
        be written generically without checking the catalogue first.
        """
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
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
        """Convenience alias: increment a counter or gauge by *value*."""
        defn = _METRIC_DEFS.get(metric_name)
        if defn is None:
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
        if defn is None or defn.kind != "gauge":
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
