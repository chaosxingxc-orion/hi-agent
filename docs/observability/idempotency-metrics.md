# Idempotency Metrics (W35-T6)

Operator-facing observability for the `IdempotencyStore` and
`IdempotencyMiddleware`. Four metrics surface cache-age distribution,
replay rate, conflict rate, and purged-record counts so operators can
distinguish a healthy retry pattern from a defective client and size
TTL/cleanup budgets.

All metrics are registered in
`hi_agent/observability/collector.py::_METRIC_DEFS` and emitted via
helper functions in `hi_agent/observability/idempotency_metrics.py`.

The in-house `MetricsCollector` exposes them on `/metrics` in
Prometheus exposition format (counters as `# TYPE counter`, histograms
rendered as `# TYPE summary` with quantiles). Tests query values via
`MetricsCollector.get_counter(name, labels=...)` and
`MetricsCollector.snapshot()`.

---

## hi_agent_idempotency_replay_total

| Property | Value |
|---|---|
| Type | counter |
| Labels | `tenant_id` (raw), `outcome` (`replayed` \| `conflict`) |
| Cardinality | 1 series per (tenant_id, outcome). Apply ops-side recording rules to bucket if needed. |
| Source | `IdempotencyStore.reserve_or_replay` (every outcome != `"created"`) |
| Use case | Replay rate tells operators how heavily clients lean on the dedup cache. A sudden spike usually means a transient upstream error caused a retry storm. |

PromQL examples:

```promql
# Replay rate per minute, all tenants
sum(rate(hi_agent_idempotency_replay_total[1m]))

# Replay rate per tenant
sum by (tenant_id) (rate(hi_agent_idempotency_replay_total[1m]))

# Conflict rate vs replay rate (should be ~0)
sum(rate(hi_agent_idempotency_replay_total{outcome="conflict"}[5m]))
  /
sum(rate(hi_agent_idempotency_replay_total[5m]))
```

Alarm guidance:
- **Replay rate > 50% of POST traffic for 5m** — possible upstream
  flake, check provider health.
- **Conflict ratio > 1% of replay traffic for 5m** — see
  `hi_agent_idempotency_conflict_total` below.

---

## hi_agent_idempotency_conflict_total

| Property | Value |
|---|---|
| Type | counter |
| Labels | `tenant_id` (raw) |
| Cardinality | 1 series per tenant. Apply ops-side recording rules to bucket if needed. |
| Source | `IdempotencyStore.reserve_or_replay` (only on `conflict` outcome — same key, different body hash) |
| Use case | A conflict means the client reused an Idempotency-Key while changing the request body. This is **never** a retry: it is a client defect or a deliberate per-request override misused as a dedup key. |

PromQL examples:

```promql
# Top tenants producing conflicts
topk(3, sum by (tenant_id) (
  rate(hi_agent_idempotency_conflict_total[10m])
))

# Conflict count over the last hour
sum(increase(hi_agent_idempotency_conflict_total[1h]))
```

Alarm guidance:
- **Any non-zero rate for >5m** — page the on-call. Healthy traffic
  produces conflicts only when a client developer is debugging.
- **Increase > 100/h on a single `tenant_id`** — escalate to the
  business owner of that tenant. They have a buggy retry path that is
  changing the request body between attempts (e.g. embedding a fresh
  timestamp inside `prompt_overrides`).

How to interpret high counts:
- **Real client bug**: client generates the Idempotency-Key once but
  rebuilds the body each retry with fresh metadata (timestamps, request
  IDs). Fix in the client SDK by hashing-the-body to derive the key, or
  by stripping volatile fields before the hash.
- **Retry on flaky network**: a healthy retry returns `replayed`, never
  `conflict`. If you see conflicts mixed with network errors, the
  client is most likely re-generating its request payload between
  attempts.

---

## hi_agent_idempotency_purged_total

| Property | Value |
|---|---|
| Type | counter |
| Labels | `tenant_id` (raw); aggregate VACUUM batches emit `tenant_id=""` as a distinct, stable series |
| Cardinality | 1 series per tenant (plus the aggregate-batch `""` series) |
| Source | `IdempotencyStore.purge_expired` (every call where `count > 0`) |
| Use case | Confirms the W35-T4 background purger is alive and sizes cleanup work. A flat-line means the purger has crashed or been mis-wired. |

PromQL examples:

```promql
# Purge rate per hour (expect non-zero whenever expired records exist)
rate(hi_agent_idempotency_purged_total[1h]) * 3600

# Total records ever purged
hi_agent_idempotency_purged_total

# Last 24h purge volume vs reserve volume (sanity bound)
increase(hi_agent_idempotency_purged_total[24h])
  /
increase(hi_agent_runs_started_total[24h])
```

Alarm guidance:
- **Zero rate for >2 * purge_interval** — the background task crashed
  or the lifespan-wired wakeup loop is stuck. Inspect the W35-T4
  background-task supervisor.
- **Burst purge >10000 records/hour** — TTL too long or write traffic
  surged. Either is benign once known but worth a dashboard note.

---

## hi_agent_idempotency_record_age_seconds

| Property | Value |
|---|---|
| Type | histogram (in-house `MetricsCollector` deque + percentiles) |
| Labels | `tenant_id` (raw) |
| Cardinality | 1 series per tenant. Apply ops-side recording rules to bucket if needed. |
| Source | `IdempotencyStore.reserve_or_replay` (every replay/conflict — observes `now - record.created_at`) |
| Use case | Distribution of "how old was the record we just hit?" — tells operators whether retries land within seconds (retry storm) or near the TTL boundary (long-running clients reusing keys). |

Recommended Prometheus bucket boundaries (exposed as
`RECORD_AGE_BUCKETS_SECONDS` in `idempotency_metrics.py`):

| Boundary | Reasoning |
|---|---|
| 1 s | Tight client retry loops; a flag for back-off bugs. |
| 60 s | Normal SDK retry-with-jitter ceiling. |
| 300 s | Browser-tab-reload class retry. |
| 1800 s | 30 minutes — typical async workflow restart. |
| 3600 s | 1 hour — long batch jobs reattempting from a checkpoint. |
| 21600 s | 6 hours — overnight scheduler retries. |
| 86400 s | 1 day — default TTL boundary, expect a small spike here. |
| 172800 s | 2 days — should be empty (records purged at 1 day TTL). |

PromQL examples (when scraped from /metrics — `MetricsCollector` emits
quantile labels rather than `_bucket` labels because it is a summary
under the hood):

```promql
# p95 record age at replay time
hi_agent_idempotency_record_age_seconds{quantile="0.95"}

# p99 — looking for outliers near or past TTL
hi_agent_idempotency_record_age_seconds{quantile="0.99"}
```

Alarm guidance:
- **p95 < 10 s** — retry storm; back-pressure or tighter client
  retry-after handling needed.
- **p95 > 0.8 * configured_TTL** — clients reusing keys near
  expiration; raise the TTL or document the expected reuse window.

---

## How to interpret high conflict counts

| Pattern | Likely cause | Action |
|---|---|---|
| Conflicts concentrated on one `tenant_id` | Client SDK bug in that tenant | Page tenant owner; share request-hash diff |
| Conflicts increase with retry rate | Client embeds volatile fields (timestamps, request IDs) in body | Tell client to strip volatile fields before hashing |
| Conflicts only on a specific endpoint | Endpoint receives multipart bodies the canonicalizer mishandles | Audit `_canonical_body_hash` in `IdempotencyFacade` |
| Conflicts during deploy | Client retried during a server upgrade that changed schema validation | Benign; conflicts should drop after a few minutes |

---

## Cardinality policy (W35 corrective C-1)

Platform-side Prometheus metrics carry raw `{tenant_id}` (and other
dimension labels). Cardinality control belongs at PromQL recording-rule
level on the operator's side, not at the metric source. This keeps
dashboard queries portable across tenants and consistent with
`hi_agent_run_*` family conventions. The legacy
`hi_agent_llm_tokens_total` metric (W31) retains a `{tenant_bucket}`
(mod-16 hash) label for backwards compatibility with W31-era
dashboards; treat it as a documented exception. New metrics MUST use
raw `{tenant_id}`. To derive a bucketed view in dashboards, use a
recording rule:

```promql
# In ops-side prometheus.yml:
- record: hi_agent:idempotency_replay_total:by_bucket
  expr: sum by (tenant_bucket) (
    label_replace(hi_agent_idempotency_replay_total, "tenant_bucket", "$1", "tenant_id", "(.{1,2}).*")
  )
```
