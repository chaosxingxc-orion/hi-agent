# Errata: W28 stale manifest 9e607a65 path relocation

**Effective**: 2026-05-02 (Wave 31; W31-D, D-11' fix)
**Status**: append-only — do not edit after publication
**Affected artifact**:
- `docs/releases/platform-release-manifest-2026-05-02-9e607a65.json` (original location, removed)
- `docs/releases/archive/W28/platform-release-manifest-2026-05-02-9e607a65.json` (current location)

## What the published artifact said (verbatim)

The W28 final manifest was originally written to:

> `docs/releases/platform-release-manifest-2026-05-02-9e607a65.json`

This location is the canonical "active manifest" path scanned by
`scripts/check_manifest_freshness.py` and similar gates. Multiple W28 intermediate
manifests (`0e855076`, `1a8b05be`, `1dc24913`, `295401c8`, `32ce75c9`, `3cf58984`,
`3f259c16`, `3fcb171c`, `4b11051d`, `5f6deb23`, `69314724`, `91689572`, `9db23868`,
`9e607a65`, `b5e00230`, `d05ed45f`, `d68d0e0d`, `de2e1eeb`, `eaecff4e`) were also
present in the active path during the W28 rewrite cycle.

## What the corrected interpretation is

The W28 manifest 9e607a65 was **moved to `docs/releases/archive/W28/` by W29-A**
(commit `9add02bc`, 2026-05-02 23:33:23 +0800) as part of the recurrence-prevention
work for the release-identity break documented in
`2026-05-02-W28-readiness-correction.md`.

Reasons for relocation:

1. The manifest's `release_head` (9e607a65) did not match `main` HEAD after the W28
   PR#17 merge (which moved `main` to 24742d7d). Per Rule 14, leaving a stale
   release-head manifest at the active path caused
   `current_verified_readiness ≤ 70` for any subsequent freshness check.
2. The W28 cycle generated 19 intermediate manifests during recovery from gate
   failures. All intermediates are now under `docs/releases/archive/W28/`.

The current canonical location for the W28 manifest is:

> `docs/releases/archive/W28/platform-release-manifest-2026-05-02-9e607a65.json`

Any reference in W23–W30 documents that points at the original
`docs/releases/platform-release-manifest-2026-05-02-9e607a65.json` path is
**broken** and should be re-read as pointing at the archive location.

The W28 archive contains 19 manifest files. The "final" W28 manifest (per the W28
delivery notice's manifest reference) is `9e607a65`, but per the
`2026-05-02-W28-readiness-correction.md` errata, the verified-readiness claim in
that manifest is not authoritative.

## Recurrence prevention

- **Untracked release artifacts gate** —
  `scripts/check_untracked_release_artifacts.py` (W17-B13). Fails CI on uncommitted
  manifests/verifications outside `docs/releases/archive/`.
- **Manifest rewrite budget gate** — `scripts/check_manifest_rewrite_budget.py`
  (W17-B19). Caps manifest rewrites per wave at 3; 4th rewrite requires
  release-captain escalation. (W28 generated 19 rewrites; this gate would now block
  that.)
- **Manifest freshness gate** — `scripts/check_manifest_freshness.py` (W16-A8).
  Fails CI when `manifest.release_head != git rev-parse HEAD`.
- **Stale manifest archive sweep** — W29-A archived all W28 intermediate manifests
  in one commit (`9add02bc`).
- **Rule 14** — Manifest is the single release fact source; only one manifest at the
  active path; intermediates archived under `docs/releases/archive/W{N}/`.
