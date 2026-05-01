#!/usr/bin/env python3
"""W16-G3: Recurrence-prevention ledger gate.

Validates docs/governance/recurrence-ledger.yaml for schema completeness.
Every entry must have all 16 required fields (non-empty) and a valid
current_closure_level from the closure taxonomy.

W19-E8 changes:
- Removed --no-strict-yaml flag and regex fallback (LB-5 fix; PyYAML is always
  required in CI; fragile fallback could silently miss enum drift).
- Added validation: metric_name, alert_rule, runbook_path must be present
  (placeholders accepted; actual path/rule existence enforced in Wave 22).
- Added validation: regression_test value that looks like a file path must
  point to an existing file (warns rather than fails for TBD values).

Exit 0: pass (all entries complete)
Exit 1: fail (missing fields or invalid closure level)
Exit 2: deferred (ledger file not found)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "docs" / "governance" / "recurrence-ledger.yaml"

_REQUIRED_FIELDS = [
    "issue_id",
    "defect_class",
    "named_instance",
    "peer_instances_audited",
    "root_cause",
    "code_fix",
    "regression_test",
    "release_gate",
    "process_change",
    "owner",
    "expiry_or_followup",
    "evidence_artifact",
    "current_closure_level",
    # W19-E8: new required fields (placeholders accepted until Wave 29)
    "metric_name",
    "alert_rule",
    "runbook_path",
]

_VALID_CLOSURE_LEVELS = {
    "component_exists",
    "wired_into_default_path",
    "covered_by_default_path_e2e",
    "verified_at_release_head",
    "operationally_observable",
}

# Prefixes that indicate a placeholder value (Wave 22 expiry placeholders)
_PLACEHOLDER_PREFIX = "TBD"


def _load_yaml(path: pathlib.Path) -> object:
    """Load the ledger YAML using PyYAML (strict; no fallback).

    PyYAML is a dev dependency. Missing it in CI means the toolchain is
    misconfigured — fail loudly rather than silently tolerating malformed
    input via a regex fallback that can miss enum drift (LB-5).
    """
    try:
        import yaml  # type: ignore[import-untyped]  expiry_wave: Wave 30
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required for recurrence_ledger validation. "
            "Install it via `pip install -e .[dev]`."
        ) from exc
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _looks_like_file_path(value: str) -> bool:
    """Return True if the value looks like a relative file path (not a sentence)."""
    # A value looks like a file path if it starts with a known directory prefix
    # and contains a file extension or path separator. We do NOT check docs/
    # (evidence artifacts) or scripts/ that are sentinel placeholders.
    stripped = value.split(",")[0].strip()  # handle "file1, file2" patterns
    path_prefixes = (
        "tests/",
        "scripts/",
        "hi_agent/",
        "agent_kernel/",
        "docs/governance/",
        "docs/delivery/",
        "docs/verification/",
        "docs/releases/",
    )
    return any(stripped.startswith(p) for p in path_prefixes)


def _check_regression_test_paths(
    entry: dict,
    issue_id: str,
    issues: list[str],
) -> None:
    """Warn if regression_test references a file path that does not exist.

    Only checks the first path token (before whitespace/dash). Does not fail
    on placeholder 'TBD' values or on sentences (natural language).
    """
    rt = entry.get("regression_test", "")
    if not isinstance(rt, str):
        return
    # Take just the first token (path ends at first space)
    first_token = rt.split()[0] if rt.split() else ""
    if not first_token or first_token.startswith(_PLACEHOLDER_PREFIX):
        return
    if not _looks_like_file_path(first_token):
        return
    candidate = ROOT / first_token
    if not candidate.exists():
        issues.append(
            f"{issue_id}: regression_test path '{first_token}' does not exist"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Recurrence-prevention ledger gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not LEDGER_PATH.exists():
        result = {
            "check": "recurrence_ledger",
            "status": "deferred",
            "reason": f"ledger not found at {LEDGER_PATH}",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: recurrence-ledger.yaml not found", file=sys.stderr)
        return 2

    try:
        data = _load_yaml(LEDGER_PATH)
    except RuntimeError as exc:
        result = {
            "check": "recurrence_ledger",
            "status": "fail",
            "reason": str(exc),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    entries = data.get("entries", []) if isinstance(data, dict) else []

    if not entries:
        result = {
            "check": "recurrence_ledger",
            "status": "fail",
            "reason": "ledger has no entries",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        return 1

    issues: list[str] = []
    for entry in entries:
        issue_id = entry.get("issue_id", "<unknown>")
        for field in _REQUIRED_FIELDS:
            val = entry.get(field)
            if val is None or val == "" or val is True:
                issues.append(f"{issue_id}: missing or empty field '{field}'")
        cl = entry.get("current_closure_level", "")
        if cl and cl not in _VALID_CLOSURE_LEVELS:
            issues.append(
                f"{issue_id}: invalid closure_level '{cl}'; "
                f"valid values: {sorted(_VALID_CLOSURE_LEVELS)}"
            )
        _check_regression_test_paths(entry, issue_id, issues)

    status = "pass" if not issues else "fail"
    result = {
        "check": "recurrence_ledger",
        "status": status,
        "entries_total": len(entries),
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        if not issues:
            print(f"PASS: {len(entries)} ledger entries all complete")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
