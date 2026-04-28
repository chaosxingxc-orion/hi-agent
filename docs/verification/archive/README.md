# Verification Artifact Archive

Historical verification artifacts (clean-env summaries, observability spine
JSON, score-cap evidence, operator-drill records, soak/chaos evidence) live
in this directory, organized by wave (`W{N}/`).

A wave subdirectory exists when a wave generated multiple intermediate
verification artifacts during gate iteration. Once a wave closes, all but
the canonical artifacts for the final HEAD are moved here.

**Convention:** `docs/verification/archive/W{N}/<sha>-<artifact-kind>.json`

The `scripts/check_untracked_release_artifacts.py` CI gate enforces that every
file under `docs/verification/` is either committed or under `archive/`.
