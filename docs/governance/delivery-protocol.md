# Hi-Agent Mandatory Delivery Protocol

Per §5 of upstream-engineering-corrective-directive-2026-04-27.md.

## 13-Step Ordered Protocol

Every upstream delivery MUST follow these steps in order. Skipping or reordering any step is prohibited.

| Step | Action | Verification Script |
|---:|---|---|
| 1 | Finish implementation and commit all code changes | `git status` — must be clean |
| 2 | Run targeted tests | `python scripts/check_targeted_default_path.py --json` |
| 3 | Run default-offline clean-env | `python scripts/verify_clean_env.py --profile default-offline` |
| 4 | Run T3 live-provider (or accepted equivalent) | `python scripts/run_t3_gate.py --provider volces` |
| 5 | Run full-chain observability E2E | `python scripts/build_observability_spine_e2e_real.py` |
| 6 | Run runtime-coupled chaos matrix | `python scripts/run_chaos_matrix.py` |
| 7 | Run 24h soak or accepted pilot (when claiming 7x24) | `python scripts/soak_24h.py --duration-seconds 21600` |
| 8 | Run all governance gates | `python scripts/build_release_manifest.py --dry-run` |
| 9 | Generate release manifest at final HEAD | `python scripts/build_release_manifest.py --wave "Wave N"` |
| 10 | Run operator drill | `python scripts/run_operator_drill.py --base-url http://127.0.0.1:8000` |
| 11 | Generate delivery notice from manifest | Notice MUST derive all facts from Step 9 manifest — no independent facts |
| 12 | Verify repository HEAD still matches manifest | `python scripts/check_release_identity.py --json` → status: pass |
| 13 | Publish (push + CI must pass) | `git push origin main` |

## Hard Rules

- **Step ordering is mandatory.** A notice generated before Step 9 manifest exists is NOT a release notice.
- **No independent facts in notices.** Functional HEAD, Manifest ID, Evidence Index — all derived from Step 9 manifest.
- **No commits after Step 9 manifest** unless they are doc-only and the docs-only gap exemption applies (≤3 commits, no .py/.toml/.yaml changed).
- **Hot-path changes invalidate T3.** Any change to files in CLAUDE.md Rule 8 hot-path list requires Step 4 to be re-run.
- **Release captain signs off** on Steps 9, 12, and 13 before push.

## Definitions

- **MUST**: mandatory — failure to follow is a process defect.
- **CLOSED**: verified at Step 12 (final HEAD) with machine-readable evidence artifact.
- **DEFERRED**: acknowledged gap; explicitly labeled; does NOT count as closure.

## Gate-Only Commit Exemption (W17/B18 — effective Wave 18)

**Problem.** During W17 closure, every fix to a `scripts/check_*.py` moved git HEAD and forced a manifest regeneration cycle (7 cycles in one wave). Most of those commits did not change product behaviour — they fixed bugs in the gate harness itself.

**Exemption.** A commit that modifies ONLY files under `scripts/_governance/` or `tests/unit/scripts/_governance/` does NOT trigger manifest regeneration provided ALL of:

1. No behavioural change observable to non-`_governance/` scripts. Verified by `tests/integration/governance/test_manifest_consensus.py` continuing to pass.
2. The commit subject is tagged `[gov-W{N}-B{M}]` (matches the W17 batch convention from `D:/.claude/plans/bugs-memoized-tarjan.md`).
3. Release captain signs the exemption in `docs/governance/recurrence-ledger.yaml`.

All OTHER `scripts/*.py` and `.github/workflows/*.yml` changes invalidate the manifest under Rule 14.

**Why limit the exemption to `_governance/`.** That subpackage has no consumers other than other governance scripts. It is pure infrastructure. Changes to general check scripts (`scripts/check_*.py`) can change CI verdicts and DO require manifest regeneration.

## Manifest Rewrite Budget (W17/B18 — effective Wave 18)

A wave may produce at most **3 release manifests** (counted by manifest files in `docs/releases/` whose `wave` field matches `current_wave()`). The 4th rewrite requires:

1. Captain escalation note in the recurrence ledger explaining the cause.
2. Override file `docs/releases/.budget.json` carrying captain SHA and ledger entry ID.

Before bumping, the captain must move stale intermediate manifests into `docs/releases/archive/W{N}/`. Enforced by `scripts/check_manifest_rewrite_budget.py` (W17/B19).
