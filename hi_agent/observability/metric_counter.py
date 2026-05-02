"""Collector-backed counter proxy with a Prometheus-style API."""

from __future__ import annotations

from dataclasses import dataclass, field

from hi_agent.observability.collector import get_metrics_collector


@dataclass(frozen=True, slots=True)
class Counter:
    """Small counter proxy that forwards to the shared metrics collector."""

    metric_name: str
    _label_values: dict[str, str] = field(default_factory=dict, repr=False)

    def labels(self, **labels: str) -> Counter:
        """Return a counter proxy bound to the supplied label set."""
        return Counter(self.metric_name, dict(labels))

    def inc(self, amount: float = 1.0) -> None:
        """Increment the counter in the shared collector, best-effort."""
        collector = get_metrics_collector()
        if collector is None:
            return
        try:
            collector.increment(
                self.metric_name,
                value=amount,
                labels=self._label_values or None,
            )
        except Exception:  # rule7-exempt: expiry_wave="Wave 30" replacement_test: wave22-tests
            return


__all__ = ["Counter"]

