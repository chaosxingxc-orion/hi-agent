# W5 Sprint — M4A-b: MCP Dynamic Discovery + Health Degradation

**Sprint window**: 2026-04-17 (same day, sequential after W4)
**Goal**: M4A Minimum Governed Tool Plane complete — MCP tools discovered dynamically, health degradation visible, release gate enforces MCP health.

---

## Ticket Tracker

| Ticket | Description | Status | Commit | Merged |
|--------|-------------|--------|--------|--------|
| HI-W5-001+002 | MCP `tools/list` dynamic discovery + merge strategy | ✅ Merged | `4631b8a` | 2026-04-17 |
| HI-W5-003 | stderr tail + health degradation (`healthy/degraded/unhealthy`) | ✅ Merged | `e02ac79` | 2026-04-17 |
| HI-W5-004 | `mcp_health` gate in release gate (Gate 7) | ✅ Merged | `da91958` | 2026-04-17 |

---

## Exit Criteria

| Check | Baseline (W4) | Target | Result |
|-------|---------------|--------|--------|
| pytest passed | 3183 | ≥ 3183 | 3204 ✅ |
| pytest failed | 0 | 0 | 0 ✅ |
| `list_tools()` on `StdioMCPTransport` | — | yes | yes ✅ |
| 6 MCP integration test scenarios (mi09–mi14) | — | all pass | all pass ✅ |
| `_merge_tools()` merge strategy | — | dynamic wins, manifest fallback | yes ✅ |
| `_stderr_reader` daemon thread | — | yes | yes ✅ |
| `get_stderr_tail()` on transport | — | yes | yes ✅ |
| Health status `degraded` / `unhealthy` | — | yes | yes ✅ |
| `/mcp/status` includes `stderr_tails` | — | yes | yes ✅ |
| `mcp_health` gate in release gate | — | yes | yes ✅ |
| Release gate now has 7 gates total | — | yes | yes ✅ |
| Unhealthy MCP server → `pass=false` in gate | — | yes | yes ✅ |
| Degraded MCP server → non-blocking (pass) | — | yes | yes ✅ |

---

## M4A: Minimum Governed Tool Plane — ACHIEVED

| Requirement | Delivered in |
|-------------|-------------|
| CapabilityDescriptor governance metadata | W4-001 |
| `probe_availability()` env-based gate | W4-001 |
| `/manifest.capability_views` structured status | W4-002 |
| `CapabilityUnavailableError` + invoker pre-check | W4-003 |
| `HybridRouteEngine` filters unavailable proposals | W4-003 |
| MCP `tools/list` dynamic discovery | W5-001 |
| Dynamic/manifest merge strategy | W5-002 |
| MCP stderr consumer + ring buffer | W5-003 |
| Health degradation (healthy/degraded/unhealthy) | W5-003 |
| `/mcp/status` stderr_tails field | W5-003 |
| Release gate `mcp_health` gate | W5-004 |

---

## New APIs Delivered

### `StdioMCPTransport` (transport.py)
- `list_tools(server_id, timeout=None)` → `list[dict]` — JSON-RPC `tools/list`
- `get_stderr_tail(n=20)` → `list[str]` — last n stderr lines from ring buffer

### `MCPBinding` (binding.py)
- `bind_all()` now does dynamic discovery via `list_tools()` when transport supports it
- `_merge_tools(server_id, preclaimed, discovered)` → `(final_names, warnings)` — static method
- `list_warnings()` → `list[str]` — merge/fallback warnings from last `bind_all()`

### `MCPHealth` (health.py)
- Status vocab expanded: `"healthy"` / `"degraded"` / `"unhealthy"` (was `"healthy"/"error"`)
- `degraded`: ping alive but stderr has error keywords
- `unhealthy`: ping failed or subprocess crashed

### `GET /mcp/status` (app.py)
- Added `stderr_tails: dict[str, list[str]]` — per-server stderr tail

### `GET /ops/release-gate` (release_gate.py)
- Gate 6 (new): `mcp_health` — skip if no servers, fail if unhealthy, pass if degraded
- Gate 7 (was 6): `prod_e2e_recent` — still always skipped

---

## Next

W6-W12 plan: see `docs/hi-agent-implementation-plan-w6-w12-2026-04-17.md`
