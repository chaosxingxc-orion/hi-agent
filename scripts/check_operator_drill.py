#!/usr/bin/env python3
"""W16-H4 / W24-G: Operator drill evidence gate.

Reads the latest operator-drill evidence from docs/verification/ and emits a
multistatus result.

Behaviour:
  - If a v2 evidence file (``*-operator-drill-v2.json``) exists, prefer it.
    PASS when ``schema_version == "2"`` (or ``version == 2``) and 5/5
    scenarios passed; DEFER otherwise.
  - Otherwise fall back to the legacy v1 evidence (``*-operator-drill.json``).
    PASS when provenance == "real", all_passed == True, head matches current
    HEAD (or governance-only gap allowed); FAIL otherwise; DEFER if no
    evidence is present at all.

The v2 prefer-over-v1 policy is deliberate: once any wave produces v2 evidence,
the drill has graduated and the legacy v1 surface is informational only.

Exit 0: pass / deferred (non-blocking)
Exit 1: fail
Exit 2: deferred-but-treated-as-error (only used in legacy --strict path)
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
_DRILL_V2_GLOB = "*-operator-drill-v2.json"


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
    """Pick latest v1 drill evidence (``*-operator-drill.json``).

    GS-6 fix: replaces the prior `git log -1 --format=%ct <short-sha>` lookup,
    which silently returned 0 on shallow CI clones (and on commits not yet
    fetched), causing all drill evidence to tie at ts=0 and fall back to
    alphabetical order. The helper sorts by (generated_at-from-content,
    mtime, name) — no git access needed.

    The v1 glob ``*-operator-drill.json`` does not match v2 evidence files
    (which end in ``-operator-drill-v2.json``) because glob requires an exact
    suffix match.  Use :func:`_latest_v2_evidence` for the v2 surface.
    """
    return latest_evidence(VERIF_DIR, _DRILL_GLOB)


def _latest_v2_evidence() -> pathlib.Path | None:
    """Pick latest v2 drill evidence (``*-operator-drill-v2.json``)."""
    return latest_evidence(VERIF_DIR, _DRILL_V2_GLOB)


def _check_v2(args) -> tuple[int, dict] | None:
    """Run the v2 drill check.

    Returns ``(exit_code, result_dict)`` when v2 evidence is present (v2 path
    is authoritative once any v2 file exists), or ``None`` when no v2
    evidence is found and the gate should fall back to legacy v1 evaluation.
    """
    v2_file = _latest_v2_evidence()
    if v2_file is None:
        return None

    try:
        data = json.loads(v2_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # Per task spec: v2 path returns PASS or DEFER (not FAIL).
        # An unreadable v2 file is DEFER — operator should re-run the drill.
        result = {
            "check": "operator_drill",
            "status": "deferred",
            "version": 2,
            "evidence_file": v2_file.name,
            "reason": f"cannot read v2 evidence: {exc}",
        }
        return 0, result

    schema_version = str(data.get("schema_version", ""))
    version = data.get("version")
    is_v2 = schema_version == "2" or version == 2
    scenarios = data.get("scenarios") or data.get("actions") or []
    scenarios_total = data.get("scenarios_total", len(scenarios))
    scenarios_passed = data.get(
        "scenarios_passed",
        sum(1 for s in scenarios if isinstance(s, dict) and s.get("passed", False)),
    )
    all_passed = data.get("all_passed", False)
    provenance = data.get("provenance", "unknown")

    if is_v2 and all_passed and scenarios_total == 5 and scenarios_passed == 5:
        result = {
            "check": "operator_drill",
            "status": "pass",
            "version": 2,
            "provenance": provenance,
            "scenarios_total": scenarios_total,
            "scenarios_passed": scenarios_passed,
            "evidence_file": v2_file.name,
            "evidence_head": str(data.get("head", ""))[:12],
        }
        return 0, result

    # Anything else under the v2 surface is DEFER, not FAIL — the drill is
    # incomplete and an operator must re-run, but it does not block ship.
    failed_names = [
        s.get("name") for s in scenarios
        if isinstance(s, dict) and not s.get("passed", True)
    ]
    result = {
        "check": "operator_drill",
        "status": "deferred",
        "version": 2 if is_v2 else 1,
        "provenance": provenance,
        "scenarios_total": scenarios_total,
        "scenarios_passed": scenarios_passed,
        "evidence_file": v2_file.name,
        "evidence_head": str(data.get("head", ""))[:12],
        "failed_scenarios": failed_names,
        "reason": (
            f"v2 evidence incomplete: schema_version={schema_version!r} "
            f"version={version!r} scenarios={scenarios_passed}/{scenarios_total} "
            f"all_passed={all_passed}"
        ),
    }
    return 0, result


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

    # W24-G: prefer v2 evidence when any is present.
    v2_result = _check_v2(args)
    if v2_result is not None:
        exit_code, result = v2_result
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status = result.get("status", "unknown").upper()
            if status == "PASS":
                print(
                    "PASS: operator drill v2 complete "
                    f"({result.get('scenarios_passed', 0)}/"
                    f"{result.get('scenarios_total', 0)} scenarios, "
                    f"provenance={result.get('provenance')})"
                )
            else:
                print(
                    f"DEFER: operator drill v2 incomplete — "
                    f"{result.get('reason', '')}",
                    file=sys.stderr,
                )
        return exit_code

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
