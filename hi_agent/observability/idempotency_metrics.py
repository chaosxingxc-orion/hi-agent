"""W35-T6: Prometheus-style metrics for the IdempotencyStore boundary.

Four metrics — declared in :mod:`hi_agent.observability.collector`'s
``_METRIC_DEFS`` registry — let operators observe the idempotency cache:

* ``hi_agent_idempotency_replay_total`` (counter, labels: tenant_id, outcome)
  — every reserve_or_replay call that did NOT create a fresh record.
* ``hi_agent_idempotency_conflict_total`` (counter, labels: tenant_id)
  — same Idempotency-Key, different body. Almost always a client defect
  (the request body changed but the dedup key didn't). High counts on a
  single tenant warrant escalation.
* ``hi_agent_idempotency_purged_total`` (counter, labels: tenant_id) —
  rows removed by :meth:`IdempotencyStore.purge_expired`. VACUUM batches
  are tenant-mixed at the SQLite layer; the aggregate batch path emits
  ``tenant_id=""`` (empty string is a distinct, intentional series for
  aggregate purges and remains stable across scrapes).
* ``hi_agent_idempotency_record_age_seconds`` (histogram, label: tenant_id)
  — distribution of record ages observed at replay/conflict time. Tall
  right-tail = clients retrying near the TTL boundary; tall left-tail =
  clients retrying within seconds (likely retry storms).

Cardinality policy (W35 corrective C-1): platform-side metric labels
carry raw ``tenant_id``. Cardinality control is an ops-side concern via
PromQL recording rules — keeping platform labels raw makes dashboards
portable across tenants and consistent with the ``hi_agent_run_*``
family. The legacy ``hi_agent_llm_tokens_total`` (W31) keeps its
``tenant_bucket`` label as a documented exception for backwards
compatibility — see ``docs/observability/idempotency-metrics.md``.

Helper-function shape mirrors :mod:`hi_agent.observability.fallback` —
public functions take primitive arguments and route through the
process-wide :class:`MetricsCollector` returned by
:func:`get_metrics_collector`. The helpers are best-effort: if no
collector is registered (test isolation, early bootstrap), they return
silently rather than raising — observability must never block business
work (Rule 7's "alarm bell" still fires via WARNING log on the
collector's own ``_report_unknown_metric`` path if the metric name is
mistyped).
"""

from __future__ import annotations

import logging
from typing import Final

from hi_agent.observability.collector import get_metrics_collector

_logger = logging.getLogger(__name__)

REPLAY_METRIC: Final[str] = "hi_agent_idempotency_replay_total"
CONFLICT_METRIC: Final[str] = "hi_agent_idempotency_conflict_total"
PURGED_METRIC: Final[str] = "hi_agent_idempotency_purged_total"
RECORD_AGE_METRIC: Final[str] = "hi_agent_idempotency_record_age_seconds"

# Recommended bucket boundaries for the age histogram. The in-house
# MetricsCollector stores raw samples (deque-backed) and computes
# percentiles on read, so these are advisory — exposed so operators
# building external Prometheus dashboards can apply equivalent buckets
# at scrape time.
RECORD_AGE_BUCKETS_SECONDS: Final[tuple[float, ...]] = (
    1.0,        # 1 s
    60.0,       # 1 min
    300.0,      # 5 min
    1800.0,     # 30 min
    3600.0,     # 1 h
    21600.0,    # 6 h
    86400.0,    # 1 d
    172800.0,   # 2 d
)


def record_replay(tenant_id: str, outcome: str) -> None:
    """Increment the replay counter for an outcome other than ``created``.

    Args:
        tenant_id: Tenant whose record was hit. Emitted as a raw label
            value so dashboards can filter/group per tenant.
        outcome: ``"replayed"`` or ``"conflict"``. Other values are
            recorded verbatim but should not occur in a Rule-3 clean call
            site.
    """
    collector = get_metrics_collector()
    if collector is None:
        return
    try:
        collector.increment(
            REPLAY_METRIC,
            labels={"tenant_id": tenant_id, "outcome": outcome},
        )
    except Exception as exc:  # rule7-exempt: observability must not propagate
        _logger.warning("idempotency_metrics.record_replay failed: %s", exc)


def record_conflict(tenant_id: str) -> None:
    """Increment the conflict counter when a key is reused with a new body.

    Pairs with :func:`record_replay` — every conflict outcome should
    increment BOTH ``hi_agent_idempotency_replay_total{outcome=conflict}``
    AND ``hi_agent_idempotency_conflict_total`` so operators can alert on
    conflicts without parsing label combinations.
    """
    collector = get_metrics_collector()
    if collector is None:
        return
    try:
        collector.increment(
            CONFLICT_METRIC,
            labels={"tenant_id": tenant_id},
        )
    except Exception as exc:  # rule7-exempt: observability must not propagate
        _logger.warning("idempotency_metrics.record_conflict failed: %s", exc)


def record_purged(count: int, tenant_id: str = "") -> None:
    """Increment the purged-records counter by ``count``.

    ``count`` is the number of rows the underlying ``DELETE`` removed.
    No-op when ``count <= 0`` so empty purge batches do not spam the
    metric.

    ``tenant_id`` is emitted as a raw label. The default empty string
    ``""`` is intentional and represents an aggregate (tenant-mixed)
    VACUUM batch at the SQLite layer — Prometheus treats the empty
    string as a distinct, stable label value, so aggregate batches form
    their own series rather than polluting per-tenant counts. Future
    per-tenant purge paths should pass the actual ``tenant_id``.
    """
    if count <= 0:
        return
    collector = get_metrics_collector()
    if collector is None:
        return
    try:
        collector.increment(
            PURGED_METRIC,
            value=float(count),
            labels={"tenant_id": tenant_id},
        )
    except Exception as exc:  # rule7-exempt: observability must not propagate
        _logger.warning("idempotency_metrics.record_purged failed: %s", exc)


def observe_age(tenant_id: str, age_seconds: float) -> None:
    """Record an age observation (seconds) for a replay/conflict outcome.

    Negative values are clamped to 0.0 — they should not occur (clock
    skew between writer and reader is tiny because both are the same
    process), but a clamp keeps the histogram interpretable.
    """
    collector = get_metrics_collector()
    if collector is None:
        return
    safe_age = max(0.0, float(age_seconds))
    try:
        collector.record(
            RECORD_AGE_METRIC,
            value=safe_age,
            labels={"tenant_id": tenant_id},
        )
    except Exception as exc:  # rule7-exempt: observability must not propagate
        _logger.warning("idempotency_metrics.observe_age failed: %s", exc)


__all__ = [
    "CONFLICT_METRIC",
    "PURGED_METRIC",
    "RECORD_AGE_BUCKETS_SECONDS",
    "RECORD_AGE_METRIC",
    "REPLAY_METRIC",
    "observe_age",
    "record_conflict",
    "record_purged",
    "record_replay",
]
