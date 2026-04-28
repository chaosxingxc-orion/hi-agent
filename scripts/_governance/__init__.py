"""Shared helpers for governance / release-gate scripts.

Single source of truth for:
  - Manifest selection (manifest_picker)
  - Evidence-artifact selection (evidence_picker)
  - Gov-only / docs-only commit-gap classification (governance_gap)
  - Current wave label and consistency (wave)

All callers in scripts/check_*.py and scripts/build_release_manifest.py
must import from this package rather than reimplementing equivalent logic
inline.  The check_no_governance_helper_bypass gate enforces this.
"""
from __future__ import annotations

__governance_helpers_version__ = "1"
