# Migration: `evolve_enabled` → `evolve_mode` (2026-04-17)

## Summary

`TraceConfig.evolve_enabled: bool` is replaced by `TraceConfig.evolve_mode: Literal["auto","on","off"]`.

## Why

The boolean flag had no way to express "follow the deployment context" (auto-on in dev, off in prod). The tri-state policy adds that without breaking explicit overrides.

## Resolution table

| `evolve_mode` | `HI_AGENT_ENV` | Effective | Source |
|---|---|---|---|
| `on` | any | `True` | `explicit_on` |
| `off` | any | `False` | `explicit_off` |
| `auto` | `dev` | `True` | `auto_dev_on` |
| `auto` | `prod` | `False` | `auto_prod_off` |

## Old behavior mapping

| Old value | Equivalent new value |
|---|---|
| `evolve_enabled=True` | `evolve_mode="on"` (always on) or `evolve_mode="auto"` (context-aware) |
| `evolve_enabled=False` | `evolve_mode="off"` |

## How to migrate

### Python config

```python
# Before
cfg = TraceConfig(evolve_enabled=True)

# After — always on
cfg = TraceConfig(evolve_mode="on")

# After — context-aware (recommended for most cases)
cfg = TraceConfig(evolve_mode="auto")

# After — always off
cfg = TraceConfig(evolve_mode="off")
```

### JSON config file

```json
// Before
{ "evolve_enabled": true }

// After
{ "evolve_mode": "auto" }
```

### Environment variable

```bash
# Before: no env var existed for this field

# After
export HI_AGENT_EVOLVE_MODE=auto   # or "on" / "off"
```

### CLI

```bash
# Force on
python -m hi_agent run --goal "..." --enable-evolve

# Force off
python -m hi_agent run --goal "..." --disable-evolve
```

## Backward compatibility

`cfg.evolve_enabled` is still accessible as a read-only property and will:
1. Emit a `DeprecationWarning`.
2. Call `resolve_evolve_effective(cfg.evolve_mode, "dev-smoke")` and return the boolean result.

The property **does not accept writes** — set `evolve_mode` directly instead.

## Audit trail

When `evolve_mode="on"` is active in a prod runtime, an audit event is written to
`.hi_agent/audit/events.jsonl` with `event="evolve.explicit_on_in_prod"`. This
provides an observable record of intentional prod-on usage.
