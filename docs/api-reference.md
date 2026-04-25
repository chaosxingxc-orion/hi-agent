# hi-agent API Reference

## Endpoints

### POST /runs

Create a new agent run.

**Request headers**

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes | `Bearer <JWT>` |
| `Idempotency-Key` | Recommended | Client-generated UUID to enable safe retries |

**Request body**

```json
{
  "goal": "Analyze quarterly revenue data",
  "profile_id": "my-agent-profile",
  "project_id": "proj-acme-q1",
  "idempotency_key": "<uuid>"  // alternative to header
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goal` | string | Yes | Natural-language goal for the run. |
| `profile_id` | string | Recommended | Runtime profile ID. Defaults to `"default"` with a warning when omitted. |
| `project_id` | string | Recommended | Project scope. Scopes memory, artifacts, and gates to a project namespace. When omitted, the response includes `X-Project-Warning: unscoped`. |
| `idempotency_key` | string | Recommended | Client-generated UUID for safe retries (alternative to the `Idempotency-Key` header). |

`profile_id` is strongly recommended; if omitted, `"default"` is used with a warning log and `hi_agent_unscoped_profile_total` counter incremented.

**Strict-mode env vars (opt-in)**

| Env var | Effect |
|---------|--------|
| `HI_AGENT_PROJECT_ID_REQUIRED=1` | `POST /runs` without `project_id` returns `400 {"error": "missing_project_id"}` instead of the warning header. |
| `HI_AGENT_PROFILE_ID_REQUIRED=1` | `POST /runs` without `profile_id` returns `400 {"error": "missing_profile_id"}` instead of the `"default"` fallback. |

These env vars are off by default. Existing callers that do not set them are unaffected.

**Response** `201 Created`

```json
{
  "run_id": "run-abc123",
  "state": "pending",
  "created_at": "2026-04-25T10:00:00Z"
}
```

**Warning headers**

If `Idempotency-Key` is missing from the request headers AND the body contains no `idempotency_key` field:

```
X-Idempotency-Warning: missing
```

If `project_id` is missing from the request body (and `HI_AGENT_PROJECT_ID_REQUIRED` is not set):

```
X-Project-Warning: unscoped
```

The run is still created. These headers are advisory — clients that require deduplication or project scoping SHOULD supply the corresponding fields.

---

## Idempotency

hi-agent implements idempotent run creation via an SQLite-backed store (WAL mode, SHA-256 payload hash).

### Contract

| Condition | HTTP status | Body |
|-----------|-------------|------|
| First request with key | `201 Created` | new run |
| Retry: same key + same body hash (original run complete) | `200 OK` | cached response snapshot (byte-identical to the `201` body) |
| Retry: same key + same body hash (original run still in-flight) | `200 OK` | `{"run_id": "<id>", "status": "pending", "note": "idempotent_replay_in_progress"}` |
| Same key + different body | `409 Conflict` | `{"error": "idempotency_conflict"}` |

### Usage

**Via header (preferred):**
```http
POST /runs
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{"goal": "Analyze data", "profile_id": "research"}
```

**Via body field (alternative):**
```json
{
  "goal": "Analyze data",
  "profile_id": "research",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

If both are present, the header takes precedence.

### Retention

Records are retained for 24 hours by default. Configure with:
```
HI_AGENT_IDEMPOTENCY_TTL_HOURS=48
```

### Replay semantics

A "replayed" response returns HTTP `200 OK` (not `201 Created`) to let clients distinguish a new creation from a replay.

**When the original run has completed**: the body is the cached response snapshot — byte-identical to the original `201` body. Clients that require strict idempotency should compare this body.

**When the original run is still in-flight**: the body is `{"run_id": "<id>", "status": "pending", "note": "idempotent_replay_in_progress"}`. Clients can poll `GET /runs/{run_id}` to observe the run's current state.

In both cases the `run_id` in the replay response is always the **original** `run_id`.

---

## Concurrency

### Rate limiting

Token-bucket middleware limits requests per tenant:
- Default: 100 requests / 60 seconds, burst 20
- Override via `HI_AGENT_RATE_LIMIT_RPM` and `HI_AGENT_RATE_LIMIT_BURST`

### Run queuing

When concurrent run capacity is exhausted, new runs enter a priority queue:
- Default: 4 concurrent runs, queue depth 16
- Configure in `hi_agent_config.json`:

```json
{
  "run_manager": {
    "max_concurrent": 16,
    "queue_size": 64
  }
}
```

Queue-full returns HTTP 503 `{"error": "queue_full"}`. Queue timeout (default 30s) returns 503 `{"error": "queue_timeout"}`.

---

## Observability

| Metric | Description |
|--------|-------------|
| `hi_agent_llm_requests_total` | LLM requests by provider/model |
| `hi_agent_llm_fallback_total` | LLM gateway fallback activations |
| `hi_agent_heuristic_route_total` | Heuristic routing activations |
| `hi_agent_mcp_config_conflict_total` | MCP server name conflicts (config vs plugin) |
| `hi_agent_unscoped_profile_total` | Runs created without a profile_id |

All metrics available at `GET /metrics` (Prometheus format).

---

## GET /runs/{run_id}

Returns run state. Terminal states: `done`, `failed`, `cancelled`.

Non-terminal runs expose `current_stage` within 30 seconds of creation. A `current_stage` of `null` for more than 60 seconds indicates a stalled run — check `GET /health`.

---

## POST /runs/{run_id}/cancel

Cancel a live run.

- `200 OK` — run reached terminal state.
- `404 Not Found` — unknown run_id.
- `409 Conflict` — run already in terminal state.
