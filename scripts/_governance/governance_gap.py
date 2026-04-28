"""Single source of truth for "is this commit-range non-functional".

Two distinct gap definitions, used by different gates:

  - GAP_DOCS_ONLY (used by manifest_freshness):
      Only docs/** changed, EXCLUDING the functional governance configs
      (score_caps.yaml, allowlists.yaml). A docs-only gap means the manifest
      is still authoritative for what's being shipped.

  - GAP_GOV_INFRA (used by evidence-freshness gates):
      Only docs/**, scripts/**, or .github/** changed. A gov-infra gap means
      observability / chaos / soak / drill evidence collected at a prior HEAD
      remains valid because no product code changed.

The W17 cycle was caused by these two definitions being divergently inlined
in build_release_manifest.py and check_manifest_freshness.py. All callers
must consume the constants and helpers from this module.
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

# Files inside docs/** that are NOT docs — they are functional governance
# configs whose changes affect ship behaviour.
FUNCTIONAL_DOCS_FILES: frozenset[str] = frozenset(
    {
        "docs/governance/score_caps.yaml",
        "docs/governance/allowlists.yaml",
    }
)

# Prefixes considered "docs-only" for the strictest gap (manifest freshness).
GAP_DOCS_ONLY: tuple[str, ...] = ("docs/",)

# Prefixes considered "governance-infrastructure-only" (looser; evidence
# freshness).  Adding scripts/ and .github/ acknowledges that gate code and CI
# config changes don't alter the product binary that evidence was collected
# against.
GAP_GOV_INFRA: tuple[str, ...] = ("docs/", "scripts/", ".github/")

GapKind = Literal["none", "docs", "scripts", "gov", "code"]


def _has_prefix(file: str, prefixes: Iterable[str]) -> bool:
    return any(file.startswith(p) for p in prefixes)


def classify_files(files: Iterable[str]) -> GapKind:
    """Pure classifier over a list of changed file paths.

    Returns:
      "none" — empty file list
      "docs" — only docs/** changed AND none are functional governance configs
      "scripts" — only scripts/** changed
      "gov" — combination of docs/scripts/.github (never code, never tests)
      "code" — any change touches hi_agent/, tests/, pyproject.toml, or a
        functional governance config inside docs/
    """
    files = list(files)
    if not files:
        return "none"

    has_docs = False
    has_scripts = False
    has_workflow = False
    has_code = False

    for f in files:
        if f in FUNCTIONAL_DOCS_FILES:
            has_code = True
        elif f.startswith("docs/"):
            has_docs = True
        elif f.startswith("scripts/"):
            has_scripts = True
        elif f.startswith(".github/"):
            has_workflow = True
        else:
            has_code = True

    if has_code:
        return "code"
    components = sum([has_docs, has_scripts, has_workflow])
    if components > 1:
        return "gov"
    if has_docs:
        return "docs"
    if has_scripts:
        return "scripts"
    return "gov"  # only workflow


def is_docs_only_files(files: Iterable[str]) -> bool:
    """Pure: True iff classify_files == 'docs'."""
    return classify_files(files) == "docs"


def is_gov_only_files(files: Iterable[str]) -> bool:
    """Pure: True iff classify_files in {'docs', 'scripts', 'gov'} (anything non-code)."""
    return classify_files(files) in {"docs", "scripts", "gov"}


def changed_files(base_sha: str, head_sha: str, repo_root: Path | None = None) -> list[str]:
    """Return list of files changed between base_sha..head_sha. Empty list on git error.

    Equal SHAs return [] (no gap).
    """
    if base_sha == head_sha:
        return []
    cwd = str(repo_root) if repo_root else None
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
            capture_output=True, text=True, cwd=cwd,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except Exception:
        return []


def is_docs_only_gap(base_sha: str, head_sha: str, repo_root: Path | None = None) -> bool:
    """True iff every commit between base..head touches only docs/** and no functional config.

    SHA equality returns True (no gap is a docs-only gap).
    Empty diff returns True (same as SHA equality).
    """
    if base_sha == head_sha:
        return True
    files = changed_files(base_sha, head_sha, repo_root)
    if not files:
        return True
    return is_docs_only_files(files)


def is_gov_only_gap(base_sha: str, head_sha: str, repo_root: Path | None = None) -> bool:
    """True iff every commit between base..head touches only docs/scripts/.github."""
    if base_sha == head_sha:
        return True
    files = changed_files(base_sha, head_sha, repo_root)
    if not files:
        return True
    return is_gov_only_files(files)


def classify_gap(base_sha: str, head_sha: str, repo_root: Path | None = None) -> GapKind:
    """Classify the commit-range gap. SHA equality returns 'none'."""
    if base_sha == head_sha:
        return "none"
    return classify_files(changed_files(base_sha, head_sha, repo_root))
