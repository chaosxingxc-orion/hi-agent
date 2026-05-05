"""Idempotency contract for the v1 northbound surface (W34-IDEMPOTENCY).

This module is the binding spec consumed by:
  - agent_server/api/middleware/idempotency.py::IdempotencyMiddleware
  - agent_server/facade/idempotency_facade.py::IdempotencyFacade
  - hi_agent/server/idempotency.py::IdempotencyStore (the persistence backend)
  - downstream RIA's platform_client/idempotency.py (per RIA R-RIA-* spec)

The module is documentation-only — it carries no runtime business logic;
the behaviours described below are enforced by the middleware + facade +
store layers above. The constants defined at the bottom of the module
are stable import targets so downstream conformance tests can pin
against the contract without scraping prose.

# scope: process-internal (the spec itself is documentation; behaviours
# are enforced at the middleware + store layers).

## Cache Scope

Idempotency keys are stored as the composite ``(tenant_id, idempotency_key)``.
Cross-tenant collisions are structurally impossible — the SQLite UNIQUE
constraint on ``(tenant_id, idempotency_key)`` enforces tenant scoping at
insertion time. Tenant A and tenant B may both legitimately submit the
key ``"K1"`` and the store treats them as two independent records.

The tenant component is sourced from the authenticated ``X-Tenant-Id``
header (validated upstream by ``TenantContextMiddleware``) — it is never
read from the request body, per R-AS-4.

## Cross-Process Replay

Idempotency state is durable. ``IdempotencyStore`` persists to
``<state_dir>/idempotency.db`` (SQLite, WAL mode) and survives kernel
restarts. A retry from the same client after the kernel has restarted,
with the same ``(tenant_id, idempotency_key, body_hash)`` triplet,
returns the cached response from the pre-restart execution rather than
creating a fresh run.

This guarantee is the foundation for downstream RIA's "send-and-forget
with crash-safe retry" pattern: RIA may retry against a freshly booted
agent-server kernel and observe byte-identical replay of the prior
response (modulo identity metadata stripped per HD-7 — see below).

Replay returns the original HTTP status code, not always 200. A retry
of a request that originally failed with HTTP 500 will replay 500; a
retry of a request that originally returned HTTP 201 will replay 201.

## TTL

Records carry ``expires_at`` (float seconds since epoch). The default
TTL is :data:`DEFAULT_TTL_SECONDS` (86400 seconds = 24 hours), set at
record-insert time in
``hi_agent/server/idempotency.py::IdempotencyStore.reserve_or_replay``.

Records older than ``expires_at`` are eligible for purge; whether purge
is proactive (background sweep) or lazy (re-insert on lookup) is an
implementation detail of ``IdempotencyStore`` and is NOT part of this
contract. Callers MUST NOT depend on either purge strategy.

## Body-Mismatch Behaviour

A retry with the same ``(tenant_id, key)`` but a different canonical
body hash returns HTTP 409 with the standard agent-server error envelope:

    {
      "error": "ConflictError",
      "message": "Idempotency-Key=<key> already used with a different body",
      "tenant_id": "<tenant_id>",
      "detail": "idempotency key reuse with body mismatch"
    }

The body hash is SHA-256 of the canonical sorted-key JSON serialization
of the request body. Empty body and non-JSON body are both deterministic
under their own sentinel forms — see
``agent_server/api/middleware/idempotency.py::_safe_decode_body``.

This guarantee holds across kernel restarts: a body-mismatch retry after
a restart still returns 409 because the persisted ``request_hash``
column is consulted against the new request's hash.

## Routes Covered

The IdempotencyMiddleware applies to every mutating northbound route:

  - POST /v1/runs                    (always guarded)
  - POST /v1/runs/{id}/cancel        (always guarded)
  - POST /v1/runs/{id}/signal        (always guarded)
  - POST /v1/skills                  (when include_skills_memory=True)
  - POST /v1/memory/write            (when include_skills_memory=True)
  - POST /v1/gates/{id}/decide       (when include_gates=True)
  - POST /v1/artifacts               (when artifact_facade is wired)

Read-only routes (every ``GET /v1/*``) bypass the middleware
unconditionally — there is no observable side effect on the kernel for
a duplicate GET, so idempotency keys would only add overhead.

## Identity-Metadata Stripping (HD-7)

Per HD-7, the persisted response snapshot has ``request_id``, ``trace_id``,
``x_request_id``, and ``_response_timestamp`` stripped before storage.
On replay these are NOT re-emitted from the snapshot — the route handler
re-decorates the replayed body with fresh values for the replaying
request. This prevents trace-lineage falsification when a second client
retries a key that a first client originally used.
"""
from __future__ import annotations

# Module-level constants so downstream conformance tests have a stable
# import target. Values must agree with the persistence backend in
# hi_agent/server/idempotency.py and the freeze snapshot in
# docs/governance/contract_v1_freeze.json.

#: Default TTL for an idempotency record, in seconds. 24 hours, matching
#: the ``ttl_seconds`` default of
#: :meth:`hi_agent.server.idempotency.IdempotencyStore.reserve_or_replay`.
DEFAULT_TTL_SECONDS: float = 86400.0

#: The scope of an idempotency key. ``"tenant"`` means the composite
#: lookup key is ``(tenant_id, idempotency_key)`` — see "Cache Scope"
#: above.
SCOPE: str = "tenant"

#: HTTP header name for the client-supplied idempotency key.
IDEMPOTENCY_HEADER: str = "Idempotency-Key"

#: HTTP header name carrying the authenticated tenant id. Sourced from
#: the auth layer, never from the request body (R-AS-4).
TENANT_HEADER: str = "X-Tenant-Id"

#: HTTP status code returned when a key is reused with a different body.
BODY_MISMATCH_STATUS: int = 409

__all__ = [
    "BODY_MISMATCH_STATUS",
    "DEFAULT_TTL_SECONDS",
    "IDEMPOTENCY_HEADER",
    "SCOPE",
    "TENANT_HEADER",
]
