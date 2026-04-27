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
