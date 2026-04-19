# W4 Sprint — M4A-a: Capability Minimum Governance

**Sprint window**: 2026-04-17 (same day, sequential after W3)
**Goal**: Capability descriptors carry governance metadata; unavailable capabilities are blocked at invoke and filtered from route proposals.

---

## Ticket Tracker

| Ticket | Description | Status | Commit | Merged |
|--------|-------------|--------|--------|--------|
| HI-W4-001 | CapabilityDescriptor governance fields + `probe_availability` | ✅ Merged | `299cacd` | 2026-04-17 |
| HI-W4-002 | `/manifest.capability_views` + `capability_contract_version` | ✅ Merged | `00e00a9` | 2026-04-17 |
| HI-W4-003 | `CapabilityUnavailableError` + invoker pre-check + route filter | ✅ Merged | `f57cf6d` | 2026-04-17 |

---

## Exit Criteria

| Check | Baseline (W3) | Target | Result |
|-------|---------------|--------|--------|
| pytest passed | 3161 | ≥ 3161 | 3183 ✅ |
| pytest failed | 0 | 0 | 0 ✅ |
| Descriptor has 4 new fields | — | yes | yes ✅ |
| `probe_availability` env-var check | — | (False, reason) | yes ✅ |
| `/manifest` has `capability_views` | — | yes | yes ✅ |
| `/manifest` retains `capabilities` list | — | yes (no break) | yes ✅ |
| `capability_contract_version` = "2026-04-17" | — | yes | yes ✅ |
| Invoker raises `CapabilityUnavailableError` | — | yes | yes ✅ |
| HybridRouteEngine filters unavailable | — | yes | yes ✅ |

---

## New Modules / Changes Delivered

### `hi_agent/capability/adapters/descriptor_factory.py`
New fields on `CapabilityDescriptor` (all backward-compatible defaults):
- `toolset_id: str = "default"`
- `required_env: dict = {}` — env vars required for availability (e.g. `{"ANTHROPIC_API_KEY": "LLM key"}`)
- `output_budget_tokens: int = 0` — 0 = unlimited
- `availability_probe: object = None` — optional `Callable[[], tuple[bool, str]]`

Factory infers `ANTHROPIC_API_KEY` in `required_env` for LLM-named capabilities (plan, reflect, reason, generate, chat, llm).

### `hi_agent/capability/registry.py`
- `probe_availability(name)` — checks required_env + calls availability_probe; never raises
- `list_with_views()` — returns `[(name, desc, status, reason), ...]` for manifest rendering

### `hi_agent/server/app.py`
- `/manifest` now includes `capability_views: list[dict]` (per-capability structured status)
- `/manifest` now includes `capability_contract_version: "2026-04-17"`
- Old `capabilities: list[str]` retained (no breaking change)

### `hi_agent/capability/invoker.py`
- `CapabilityUnavailableError(capability_name, reason)` — typed exception with both attributes
- `CapabilityInvoker.invoke()` pre-check via `probe_availability` before handler call
- Backward-compatible: `hasattr` guard, no break when registry lacks the method

### `hi_agent/route_engine/hybrid_engine.py`
- Optional `capability_registry=None` keyword param added to `__init__`
- `_filter_unavailable(proposals)` filters proposals whose `action_kind` fails `probe_availability`
- Applied to both rule and LLM proposal paths in `propose_with_provenance()`

---

## Deferred to W5+

- ARCHITECTURE.md Capability Plane section update
- Downstream contract change notice for `capability_views` field
- `RuleRouteEngine` / `LLMRouteEngine` direct filter (not needed — filter is in `HybridRouteEngine` wrapper)
- `toolset_id`-based routing policies
