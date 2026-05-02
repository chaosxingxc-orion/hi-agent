# Errata: `cap_reason: "all gates pass"` is too vague (Rule 14)

**Effective**: 2026-05-02 (Wave 31; W31-D, D-17' fix)
**Status**: append-only — do not edit after publication
**Affected artifacts** (published with the vague cap_reason language):
- `docs/releases/platform-release-manifest-2026-05-02-aa073e12.json:4052` (W30 final manifest, current active)
- `docs/releases/archive/W28/platform-release-manifest-2026-05-02-9e607a65.json:4774` (W28 final manifest, archived)
- All W28 intermediate manifests in `docs/releases/archive/W28/` carrying the same `cap_reason` field
- `docs/releases/archive/W29/platform-release-manifest-2026-05-02-23a30d78.json` (likely also affected — to be verified by future wave audit)

## What the published artifact said (verbatim)

From `docs/releases/platform-release-manifest-2026-05-02-aa073e12.json` line 4052:

> ```json
> "cap_reason": "all gates pass",
> ```

This appears in the `scorecard` object alongside `cap: null`, `current_verified_readiness: 94.55`, and similar verified-tier fields.

## What the corrected interpretation is

The phrase **"all gates pass"** is on the Rule 14 forbidden-phrases list:

> "Forbidden phrases (prohibited unless current-HEAD evidence in the manifest
> supports them): 'closed', 'fully closed', 'complete', **'all green'**,
> 'release-ready', 'verified 80+', 'production-ready', '7×24 ready',
> 'L3 unchanged', 'default path closed'."

"All gates pass" is functionally equivalent to "all green" and carries the same risk:
it asserts a global state (no gate produced a fail) without naming the SHA at which
the assertion was verified. A reader looking at the manifest later cannot tell
whether the assertion was verified at the manifest's `release_head`, at some
intermediate SHA, or against an out-of-date evidence file.

The corrected language for `cap_reason` when no cap is applied is:

> `"no gate-fail conditions triggered at SHA <X>"`

where `<X>` is the manifest's `release_head` short-SHA. This:

1. Names the SHA explicitly (Rule 14 §4.4 — score derived from manifest facts).
2. Asserts the absence of triggers, not a positive global state (avoids the
   forbidden-phrase pattern).
3. Is unambiguous when the manifest is read in archive — the reader can verify the
   SHA is the manifest's own `release_head`.

## Recurrence prevention

- **Source script fix** — `scripts/build_release_manifest.py` updated in W31-D
  (Task 8) to emit
  `cap_reason: "no gate-fail conditions triggered at SHA <release_head_short>"`
  when `cap_factors == []`. The previous `"all gates pass"` literal is removed.
- **Per Rule 14**, published manifests are NOT rewritten — the past instances above
  remain in the repo with the original (vague) language. This errata documents the
  past instances and the language fix.
- **Future audit hook**: a future wave should add a CI gate that scans manifest
  `cap_reason` fields against the Rule 14 forbidden-phrase list. (Not added in
  W31-D; would require the doc-truth gate to expand its scope.)

## Why this errata exists

This errata exists because of the W31 multi-track audit finding D-17':

> "cap_reason language fix — `cap_reason: 'all gates pass'` is too vague; specific
> language: `cap_reason: 'no gate-fail conditions triggered at SHA <X>'`."

The fix is in the source script for future manifests; past manifests retain the
vague language but are now annotated by this errata.
