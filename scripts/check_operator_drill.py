#!/usr/bin/env python3
"""W16-H4: Operator drill evidence gate.

Reads the latest *-operator-drill.json from docs/verification/ and confirms:
  - provenance == "real"
  - all_passed == True
  - Evidence head matches current repository HEAD (or is within docs-only gap)

Exit 0: pass
Exit 1: fail
Exit 2: deferred (no evidence found)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

from _governance.evidence_picker import latest_evidence
from _governance.governance_gap import is_gov_only_gap

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERIF_DIR = ROOT / "docs" / "verification"

# Tightened from "*operator-drill*.json" to "*-operator-drill.json" (GS-5):
# the producer always writes "{sha}-operator-drill.json", so requiring the
# hyphen before "operator-drill" rejects any accidentally-named sibling file
# that doesn't follow the SHA prefix convention.
_DRILL_GLOB = "*-operator-drill.json"


def _git_head() -> str:
    r = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def _gov_only_gap(base_sha: str, head_sha: str) -> bool:
    """Backward-compat wrapper for the canonical helper (G-3 fix)."""
    return is_gov_only_gap(base_sha, head_sha, repo_root=ROOT)


def _latest_drill_evidence() -> pathlib.Path | None:
    """Pick latest drill evidence via canonical helper.

    GS-6 fix: replaces the prior `git log -1 --format=%ct <short-sha>` lookup,
    which silently returned 0 on shallow CI clones (and on commits not yet
    fetched), causing all drill evidence to tie at ts=0 and fall back to
    alphabetical order. The helper sorts by (generated_at-from-content,
    mtime, name) — no git access needed.
    """
    return latest_evidence(VERIF_DIR, _DRILL_GLOB)


def main() -> int:
    parser = argparse.ArgumentParser(description="Operator drill evidence gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--allow-docs-only-gap",
        action="store_true",
        default=False,
        dest="allow_docs_only_gap",
        help=(
            "Permit HEAD mismatches when all commits between evidence HEAD and "
            "current HEAD touch only governance files (docs/, scripts/, .github/)."
        ),
    )
    args = parser.parse_args()

    evidence_file = _latest_drill_evidence()
    if evidence_file is None:
        result = {
            "check": "operator_drill",
            "status": "deferred",
            "reason": "no operator drill evidence found in docs/verification/",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no operator drill evidence", file=sys.stderr)
        return 2

    try:
        data = json.loads(evidence_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result = {
            "check": "operator_drill",
            "status": "fail",
            "reason": f"cannot read evidence: {exc}",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    provenance = data.get("provenance", "unknown")
    all_passed = data.get("all_passed", False)
    evidence_head = data.get("head", "")

    current_head = _git_head()
    head_match = (
        not evidence_head
        or not current_head
        or evidence_head[:12] == current_head[:12]
    )

    issues = []
    if provenance != "real":
        issues.append(f"provenance={provenance!r} (expected 'real')")
    if not all_passed:
        actions = data.get("actions", [])
        failed = [a.get("name") for a in actions if not a.get("passed", True)]
        issues.append(f"all_passed=False; failed actions: {failed}")
    if not head_match:
        if args.allow_docs_only_gap and _gov_only_gap(evidence_head, current_head):
            pass  # governance-only commits after drill — evidence still valid
        else:
            issues.append(
                f"evidence head {evidence_head[:12]} != current HEAD {current_head[:12]}"
            )

    status = "pass" if not issues else "fail"
    result = {
        "check": "operator_drill",
        "status": status,
        "provenance": provenance,
        "all_passed": all_passed,
        "evidence_file": evidence_file.name,
        "evidence_head": evidence_head[:12] if evidence_head else "",
        "current_head": current_head,
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        if not issues:
            print("PASS: operator drill complete (provenance:real, all actions passed)")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
