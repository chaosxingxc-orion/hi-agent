#!/usr/bin/env python3
"""CLEAN-D: Dead code dependency analysis.

Finds Python modules with zero inbound imports AND no recent git activity
(>7 days untouched). Cross-references with tests/ references.

Outputs docs/governance/dead-code-audit-2026-05-02.md.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
_SCAN_DIRS = ["hi_agent", "agent_kernel", "agent_server"]
_SKIP_STEMS = {"__init__", "__main__", "conftest"}


def _git_grep_count(stem: str) -> int:
    r = subprocess.run(
        ["git", "grep", "-l", stem, "--", "*.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT)
    )
    return len(r.stdout.strip().splitlines()) if r.stdout and r.stdout.strip() else 0


def _recent_activity(path: pathlib.Path) -> bool:
    r = subprocess.run(
        ["git", "log", "--since=7 days ago", "-1", "--", str(path.relative_to(ROOT))],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT)
    )
    return bool(r.stdout and r.stdout.strip())


def main() -> None:
    candidates = []
    for scan_dir in _SCAN_DIRS:
        for pyf in sorted((ROOT / scan_dir).rglob("*.py")):
            if "__pycache__" in pyf.parts:
                continue
            if pyf.stem in _SKIP_STEMS:
                continue
            ref_count = _git_grep_count(pyf.stem)
            if ref_count <= 1 and not _recent_activity(pyf):
                candidates.append((str(pyf.relative_to(ROOT)), ref_count))

    out_path = ROOT / "docs" / "governance" / "dead-code-audit-2026-05-02.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Dead Code Audit — 2026-05-02\n\n")
        f.write("Methodology: grep-based inbound-import count + git log recent activity.\n")
        f.write("Candidates: `<=1` grepped references AND no git activity in past 7 days.\n\n")
        f.write("**IMPORTANT**: Stem-based grep has false negatives (dynamic imports) and\n")
        f.write("false positives (short stems matching unrelated identifiers). Review before\n")
        f.write("deleting anything.\n\n")
        f.write(f"**Candidates found: {len(candidates)}**\n\n")
        if candidates:
            f.write("| Module | Grepped refs |\n|---|---|\n")
            for path, refs in candidates:
                f.write(f"| `{path}` | {refs} |\n")
        else:
            f.write("No zero-inbound candidates found.\n")
        f.write("\n## Proposed Deletions\n\n")
        f.write("None proposed in W28. All candidates require manual verification before deletion.\n")
        f.write("Formal deletion of confirmed dead code deferred to W29.\n")

    print(f"Written: {out_path}")
    print(f"Candidates: {len(candidates)}")


if __name__ == "__main__":
    main()
