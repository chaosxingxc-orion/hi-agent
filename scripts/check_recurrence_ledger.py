#!/usr/bin/env python3
"""W16-G3: Recurrence-prevention ledger gate.

Validates docs/governance/recurrence-ledger.yaml for schema completeness.
Every entry must have all 13 required fields (non-empty) and a valid
current_closure_level from the closure taxonomy.

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
]

_VALID_CLOSURE_LEVELS = {
    "component_exists",
    "wired_into_default_path",
    "covered_by_default_path_e2e",
    "verified_at_release_head",
    "operationally_observable",
}


def _load_yaml(path: pathlib.Path) -> object:
    try:
        import yaml  # type: ignore[import-untyped]  expiry_wave: Wave 17
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ImportError:
        pass
    # Minimal fallback: parse with a hand-rolled YAML-key reader (no deps)
    import re
    text = path.read_text(encoding="utf-8")
    entries: list[dict] = []
    current: dict = {}
    for line in text.splitlines():
        # Detect new entry start: "  - issue_id:"
        m_start = re.match(r"^\s{2}-\s+(\w+):\s*(.*)", line)
        if m_start:
            if current:
                entries.append(current)
            current = {m_start.group(1): m_start.group(2).strip()}
            continue
        # Continuation key: "    defect_class: ..."
        m_key = re.match(r"^\s{4,}(\w+):\s*(.*)", line)
        if m_key and current:
            val = m_key.group(2).strip().strip('"').strip("'")
            current[m_key.group(1)] = val or True
    if current:
        entries.append(current)
    return {"entries": entries}


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

    data = _load_yaml(LEDGER_PATH)
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
