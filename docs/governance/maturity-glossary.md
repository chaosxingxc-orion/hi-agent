# Capability Maturity Glossary

Maps retired vocabulary to the L0–L4 maturity model (Rule 13, effective Wave 9+).

## Vocabulary Mapping

| Retired label | L-level | Notes |
|---|---|---|
| `experimental` | L1 | Tests exist, not default path |
| `implemented_unstable` | L1 | Tests exist, not default path |
| `public_contract` | L2 | Schema/API stable, docs + tests full |
| `production_ready` | L3 | Research/prod default-on, migration + observability |

## L-level Definitions

| Level | Name | Criterion |
|---|---|---|
| L0 | demo code | Happy path only, no stable contract |
| L1 | tested component | Unit/integration tests exist, not default path |
| L2 | public contract | Schema/API/state machine stable, docs + tests full |
| L3 | production default | research/prod default-on, migration + observability |
| L4 | ecosystem ready | Third-party can register/extend/upgrade/rollback without source |

## Usage

Every `CapabilityDescriptor` in the registry must carry an explicit `maturity_level` field.
Enforced by `scripts/check_capability_maturity.py`.

Legacy labels in released documents (`docs/downstream-responses/2026-04-25-*.md`) are
preserved verbatim — those are immutable release artifacts. This glossary is the
authoritative mapping for interpreting them.
