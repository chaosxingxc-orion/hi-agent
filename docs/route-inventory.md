# Route Allowlist Inventory

Tracks the count of scope-unset routes and allowlist entries per wave. Updated by the GOV track at each wave close.

| Wave | Total handlers | No-scope count | Allowlist total | Allowlist expired | High-risk count | Delta (allowlist) |
|---|---|---|---|---|---|---|
| Wave 10.5 | 60 | 17 | 34 | 0 | 3 | baseline |
| Wave 11 | TBD | TBD | TBD | 0 | TBD | TBD |

**Definition:**
- `No-scope`: route handler has no tenant scope annotation
- `Allowlist total`: entries in NO_SCOPE_ALLOWLIST
- `Allowlist expired`: entries with expiry_wave <= current wave
- `High-risk`: entries requiring cross-tenant negative test coverage
