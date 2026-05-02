# Errata — append-only corrections to published artifacts

**Effective from**: Wave 31 (W31-D, 2026-05-03 — D-10'/D-11'/D-12' fix).

This directory holds **append-only** corrections to artifacts that were already
published (delivery notices, release manifests, signoff JSONs). Per Rule 14, published
artifacts are NOT rewritten in-place — when a defect is found in a published artifact,
the correction lands here as a new file with an ISO timestamp prefix.

---

## Append-only discipline

- Files in this directory are **never edited after they land**, except to fix typos
  in the corrected interpretation. The "what the published artifact said" section is
  immutable.
- New errata files use the filename `YYYY-MM-DD-<wave>-<short-description>.md`.
- Each file MUST include:
  - ISO timestamp at the top (`Effective: YYYY-MM-DD`).
  - **What the published artifact said** (verbatim quote, with file path + line ref).
  - **What the corrected interpretation is** (with reasoning).
  - **Where the recurrence-prevention lives** (CI gate, ledger entry, rule).

---

## Directory contents (chronological)

| Date | Wave | Title | Subject |
|---|---|---|---|
| 2026-05-02 | W28 | `2026-05-02-W28-readiness-correction.md` | W28 verified=94.55 readiness claim retroactively capped |
| 2026-05-02 | W28 | `2026-05-02-W28-manifest-path-relocation.md` | W28 stale manifest 9e607a65 path relocation |
| 2026-05-02 | W28 | `2026-05-02-W28-cap-reason-language.md` | `cap_reason: "all gates pass"` is too vague (W31-D D-17') |

(Future entries appended below this line.)

---

## How to publish a new errata file

1. Identify the published artifact (must already be in repo with a manifest_id /
   notice-id / signoff-id).
2. Create `docs/governance/errata/YYYY-MM-DD-<wave>-<slug>.md` using the template
   below.
3. Add a row to the chronological table above.
4. Commit with message `[W<N>-<track>] D-<id>' errata: <slug>`.

### Template

```markdown
# Errata: <subject>

**Effective**: YYYY-MM-DD (Wave <N>; W<N>-<track>, D-<id>')
**Status**: append-only — do not edit after publication
**Affected artifact**: `<file-path>` (`<artifact-id>`)

## What the published artifact said (verbatim)

> <verbatim quote with file:line>

## What the corrected interpretation is

<corrected reading + reasoning + manifest/notice references>

## Recurrence prevention

- CI gate: `<script-path>` (added at <commit-sha>)
- Ledger entry: `docs/governance/recurrence-ledger.yaml` (`<entry-id>`)
- Rule: <CLAUDE.md rule reference>
```
