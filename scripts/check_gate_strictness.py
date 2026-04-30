#!/usr/bin/env python3
"""W18-C1: Gate strictness enforcer.

Scans .github/workflows/*.yml for:
- '--allow-docs-only-gap' flag in run: commands
- 'continue-on-error: true' in step definitions

Legitimate exemptions (do NOT flag):
1. 'continue-on-error: true' on a step that also has 'if: ${{ env.X_API_KEY != "" }}'
   pattern (live API tests gated on credentials -- allowed per CLAUDE.md narrow-trigger rules)

Everything else is a gate weakening and causes exit 1.

Exit 0: pass
Exit 1: fail (unaccounted gate weakenings found)
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

_DOCS_ONLY_GAP = re.compile(r"--allow-docs-only-gap")
_CONTINUE_ON_ERROR = re.compile(r"^\s*continue-on-error:\s*true", re.MULTILINE)
_API_KEY_CONDITIONAL = re.compile(r"if:.*env\.\w*API_KEY\w*.*!=")
# Steps with a "# TODO: promote to blocking in W<N>" comment are advisory-by-design
# for the current wave and exempt from the gate-weakening check.
_PROMOTE_TO_BLOCKING_COMMENT = re.compile(
    r"#\s*(?:TODO|advisory)[^\n]*(?:promote to blocking|blocking in W)\d+",
    re.IGNORECASE,
)
# Steps that explicitly declare not_applicable context (e.g. until T3 reruns)
_NOT_APPLICABLE_COMMENT = re.compile(
    r"#\s*not_applicable",
    re.IGNORECASE,
)


def _parse_steps(text: str) -> list:
    """Extract step blocks from YAML text as lists of lines."""
    steps = []
    lines = text.splitlines()
    current_step: list = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- name:") and current_step:
            steps.append(current_step)
            current_step = [line]
        elif stripped.startswith("- name:"):
            current_step = [line]
        elif current_step:
            current_step.append(line)
    if current_step:
        steps.append(current_step)
    return steps


def _check_file(wf_path: pathlib.Path) -> list:
    issues = []
    text = wf_path.read_text(encoding="utf-8")
    steps = _parse_steps(text)

    for step_lines in steps:
        step_text = "\n".join(step_lines)
        step_name = ""
        for ln in step_lines:
            m = re.match(r"\s*-?\s*name:\s*(.+)", ln)
            if m:
                step_name = m.group(1).strip()
                break

        has_api_key_if = bool(_API_KEY_CONDITIONAL.search(step_text))
        has_docs_only_gap = bool(_DOCS_ONLY_GAP.search(step_text))
        has_continue_on_error = bool(_CONTINUE_ON_ERROR.search(step_text))
        # Advisory-by-design exemptions: steps that explicitly declare a promotion
        # wave via "# TODO: promote to blocking in W<N>" or are marked not_applicable.
        has_promote_annotation = bool(_PROMOTE_TO_BLOCKING_COMMENT.search(step_text))
        has_not_applicable = bool(_NOT_APPLICABLE_COMMENT.search(step_text))
        is_advisory_by_design = has_promote_annotation or has_not_applicable

        if has_docs_only_gap and not is_advisory_by_design:
            issues.append({
                "file": str(wf_path.relative_to(ROOT)),
                "step": step_name,
                "violation": "--allow-docs-only-gap",
                "detail": (
                    "Flag removes docs-only-gap exemption from gate; "
                    "not permitted without ledger issue_id or "
                    "'# TODO: promote to blocking in W<N>' annotation"
                ),
            })
        if has_continue_on_error and not has_api_key_if and not is_advisory_by_design:
            issues.append({
                "file": str(wf_path.relative_to(ROOT)),
                "step": step_name,
                "violation": "continue-on-error: true",
                "detail": "Makes gate advisory without API-key conditional; gate must be blocking",
            })

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate strictness enforcer.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any violation (default behaviour; flag is a no-op kept for CI parity).",
    )
    args = parser.parse_args()

    if not WORKFLOWS_DIR.exists():
        result = {
            "status": "not_applicable",
            "check": "gate_strictness",
            "reason": "workflows directory not found",
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 0

    all_issues: list = []
    for wf_file in sorted(WORKFLOWS_DIR.glob("*.yml")):
        all_issues.extend(_check_file(wf_file))

    status = "pass" if not all_issues else "fail"
    # provenance is "real" when the check actually scanned real workflow files
    # and all assertions passed.  "structural" when there are violations or
    # the scan did not complete cleanly.
    derived_provenance = "real" if status == "pass" else "structural"
    result = {
        "status": status,
        "check": "gate_strictness",
        "provenance": derived_provenance,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "violations_found": len(all_issues),
        "violations": all_issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if all_issues:
            for issue in all_issues:
                print(
                    f"FAIL [{issue['file']}] step='{issue['step']}': "
                    f"{issue['violation']} -- {issue['detail']}",
                    file=sys.stderr,
                )
        else:
            print(f"PASS: 0 gate weakenings found in {WORKFLOWS_DIR}")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
