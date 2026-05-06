# tests — Profile + Harness Guide

> **Last refreshed:** 2026-05-06 (W35 corrective close + W36 plans). HEAD `276917d8`.
> **Audience:** anyone writing or running tests in this repo.

This directory holds the test suite for the three top-level packages (`agent_kernel`, `hi_agent`, `agent_server`) plus governance and harness fixtures. Test discovery and profile selection are governed by `tests/profiles.toml` (machine-readable, single source of truth per CLAUDE.md Rule 16).

---

## Directory layout

| Path | Layer (Rule 4) | What it tests |
|---|---|---|
| `tests/unit/` | L1 unit | One function per test; mocks only external network or fault injection. |
| `tests/integration/` | L2 integration | Real components wired together; **zero mocks on the subsystem under test** (Rule 4). |
| `tests/e2e/` | L3 E2E | Drive through HTTP / CLI / public API; assert on observable outputs only. |
| `tests/contract/` | L1/L2 | Protocol conformance (e.g. `DedupeStore` protocol across all backends). |
| `tests/posture/` | L1/L2 | Posture-aware paths — every new strict branch tested in both `dev` and `research`. |
| `tests/agent_kernel/` | L1/L2 | Kernel-package-scoped tests. |
| `tests/agent_server/{unit,integration,e2e}/` | L1/L2/L3 | Agent-server-scoped tests. |
| `tests/runtime_adapter/` | L2 | Tests for `hi_agent/runtime_adapter/`. |
| `tests/server/` | L2 | Tests for `hi_agent/server/` route handlers and stores. |
| `tests/security/` | L1 | Security-boundary tests (path traversal, auth bypass, scope escape). |
| `tests/chaos/` + `tests/integration/test_chaos_matrix.py` | L2/L3 | Runtime-coupled chaos scenarios (Rule 8 §3 chaos coupling). |
| `tests/operator_drill_v2/` | L3 | Operator-shape gate drill scenarios (Rule 8). |
| `tests/perf/` | soak | 1 h / 24 h / 72 h soak drivers. |
| `tests/governance/` | L1 | Tests for the governance gate scripts themselves. |
| `tests/scripts/` | L1 | Tests for `scripts/` library helpers. |
| `tests/characterization/` | L1 | Characterization tests pinning current behaviour during refactor. |
| `tests/fixtures/`, `tests/helpers/`, `tests/_helpers/`, `tests/snapshots/`, `tests/golden/` | — | Shared fixtures, helpers, snapshot/golden data. |
| `tests/conftest.py` | — | Top-level pytest configuration + fixture exposure. |
| `tests/profiles.toml` | — | **Profile definitions (Rule 16 single source of truth).** |

---

## Test profile taxonomy (Rule 16)

Seven profiles, in increasing scope. Definitions live in `tests/profiles.toml`; do not duplicate them elsewhere.

| Profile | Targets | Network | Real LLM | Secrets | Timeout | Use |
|---|---|---|---|---|---|---|
| `smoke` | 10 hand-picked unit files | no | no | no | 120 s | quick local sanity |
| `default-offline` | `tests/{unit,contract,security,agent_kernel}` + `tests/agent_server/{unit,integration,e2e}` | **no** | **no** | **no** | 600 s | clean-env CI gate |
| `release` | `tests/{unit,integration,contract,security,agent_kernel,runtime_adapter,server}` | no | no | no | 1800 s | release-gate composite |
| `live_api` | unit + integration + contract + security | yes | yes | yes | 1800 s | manual / scheduled real-LLM |
| `prod_e2e` | unit + integration | yes | yes | yes | 3600 s | Rule 8 operator-shape gate |
| `soak` | `tests/perf` | yes | yes | yes | 90000 s (25 h) | 1 h / 24 h / 72 h drivers |
| `chaos` | `tests/integration/test_chaos_matrix.py` | no | no | no | 3600 s | runtime-coupled chaos matrix |

**`default-offline` invariants (binding per Rule 16):**

- No real network calls.
- No real LLM calls.
- No requirement on external secrets.
- The clean-env wrapper emits truthful evidence JSON even when pytest fails / times out / crashes (`status=failed`, `failure_reason` non-null). It MUST NOT write zero counts when the actual summary is unavailable.
- Wrapper is portable across Windows + Linux without per-OS encoding env vars.

---

## Quickstart

```bash
# Default-offline (the canonical CI gate; no network, no LLM, no secrets):
python scripts/verify_clean_env.py

# Run a single integration test, fail fast, quiet:
python -m pytest tests/integration/test_idempotency_ttl_purge.py -x -q

# Run the smoke profile (~2 min):
python -m pytest $(python -c "import tomllib; print(' '.join(tomllib.load(open('tests/profiles.toml','rb'))['profiles']['smoke']['targets']))")

# Run with marker exclusion (e.g. exclude live_api):
python -m pytest tests -m "not live_api and not external_llm"
```

`scripts/verify_clean_env.py` is the binding entry — it reads `tests/profiles.toml`, runs the chosen profile in a clean subprocess, and writes `docs/verification/<sha>-default-offline-clean-env.json` for the manifest.

---

## Marker conventions

Markers are declared in `pyproject.toml` and asserted by `scripts/check_pytest_markers.py`. The active set:

| Marker | Meaning |
|---|---|
| `pytest.mark.integration` | Layer-2 integration test (real components wired). |
| `pytest.mark.e2e` | Layer-3 end-to-end test. |
| `pytest.mark.real_llm` | Calls a real LLM provider; excluded from `default-offline`. |
| `pytest.mark.live_api` | Calls real network APIs; excluded from `default-offline`. |
| `pytest.mark.external_llm` | Synonym variant; excluded from `default-offline`. |
| `pytest.mark.network` | Requires real network; excluded from `default-offline`. |
| `pytest.mark.requires_secret` | Requires environment-loaded secret. |
| `pytest.mark.windows_unsafe` | Skipped on Windows in `default-offline`. |
| `pytest.mark.soak` | Soak driver — only `soak` profile. |
| `pytest.mark.chaos` | Chaos scenario — only `chaos` profile. |
| `pytest.mark.slow` | Long-running but valid in `default-offline`; surface in summary. |

Skips must use `@pytest.mark.skip(reason="awaiting real implementation")` form when a dependency is absent (Rule 4); never silently fake the dependency.

---

## TDD-RED discipline (R-AS-5)

Every new route handler in `agent_server/api/routes_*.py` requires a `# tdd-red-sha: <sha>` comment in the handler source, referencing the commit SHA of the failing test (RED stage). Enforced by `scripts/check_tdd_evidence.py`. The test that turned RED first is the canonical regression test for that route.

This rule does NOT apply to `agent_kernel/service/http_server.py` (kernel-internal) or to test-only / governance code.

---

## Honesty rules (Rule 4)

- Layer-2 tests never `MagicMock` the subsystem under test. If you find yourself patching the very class you're testing, the test is misclassified.
- Layer-3 tests assert on observable outputs (HTTP response, CLI output, file artifact) — never on internal variables.
- A test that passes when the subject raises is a lie; assert the typed failure explicitly.
- "Any terminal status accepted" is documentation, not a test.

`scripts/check_test_honesty.py` and `scripts/check_vacuous_asserts.py` enforce these. `scripts/audit_unit_test_purity.py` flags integration-style mocks in unit tests.

---

## Posture coverage (Rule 11)

Every `if posture.is_strict` branch must have:

1. A test under `tests/posture/` (or in the relevant subsuite) for the dev path (allow / warn).
2. A test for the research path (reject / raise).

`scripts/check_posture_coverage.py` enforces this. The shared helper `assert_research_posture_required` in `hi_agent/config/posture.py` (extension landing in W36-A5) is the single construction path for boot-time strict assertions.

---

## Pointers

- Profile definitions → `tests/profiles.toml`
- Clean-env runner → `scripts/verify_clean_env.py`
- Engineering rules → `../CLAUDE.md` (Rule 4 testing, Rule 11 posture, Rule 16 profiles)
- Governance gate scripts → `../scripts/README.md`
- Operator drill scenarios → `tests/operator_drill_v2/` + `scripts/run_operator_drill.py`
- Architecture overview → `../ARCHITECTURE.md`, `../hi_agent/ARCHITECTURE.md`, `../agent_kernel/ARCHITECTURE.md`
