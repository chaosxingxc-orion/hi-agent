# Release Manifest Archive

Historical release manifests live in this directory, organized by wave (`W{N}/`).

A wave subdirectory exists when a wave generated multiple intermediate manifest
files during gate iteration. Once a wave closes, all but the final canonical
manifest are moved here to keep `docs/releases/` itself uncluttered while
preserving the audit trail.

**Convention:** `docs/releases/archive/W{N}/platform-release-manifest-<date>-<sha>.json`

The `scripts/check_untracked_release_artifacts.py` CI gate enforces that every
file under `docs/releases/` is either committed or under `archive/`. New
manifests that stay at the top level must be committed; older or superseded
manifests must be moved here.

## Contents

- `W17/` — manifests generated during the W17 closure thrash (gate
  infrastructure was being debugged in-place; see W17 audit for context).
