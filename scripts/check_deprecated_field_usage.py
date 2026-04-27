#!/usr/bin/env python3
"""CI gate: prevent new usage of deprecated TeamRun fields.

Scans hi_agent/**/*.py for reads/writes of pi_run_id (outside the
compatibility allowlist). Fails if found.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _governance_json import emit_result

ROOT = Path(__file__).parent.parent
ALLOWLIST = {
    "hi_agent/contracts/team_runtime.py",       # defines the field + deprecation logic
    "hi_agent/server/team_run_registry.py",     # migration read/write fallback
}


def check_pi_run_id_usage(path: Path) -> list[str]:
    try:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        # Path is outside ROOT (e.g. tmp_path in tests); treat as unchecked.
        rel = str(path)
    if rel in ALLOWLIST:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "pi_run_id":
            issues.append(f"  {rel}:{node.lineno}: .pi_run_id access 鈥?use .lead_run_id instead")
        if isinstance(node, ast.keyword) and node.arg == "pi_run_id":
            issues.append(f"  {rel}:{node.lineno}: pi_run_id= kwarg 鈥?use lead_run_id= instead")
    return issues


def _parse_deprecated_error(text: str) -> dict:
    """Parse error string into structured dict."""
    import re
    # Format: "  file:line: message"
    m = re.match(r"\s+([^:]+):(\d+): (.*)", text)
    if m:
        return {"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)}
    return {"text": text.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check deprecated field usage")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    args = parser.parse_args()

    errors = []
    for py_file in (ROOT / "hi_agent").rglob("*.py"):
        errors.extend(check_pi_run_id_usage(py_file))

    if args.json:
        structured = [_parse_deprecated_error(e) for e in errors]
        emit_result(
            "deprecated_field_usage",
            "pass" if not errors else "fail",
            violations=structured,
            counts={"total": len(errors)},
        )

    if errors:
        print("FAIL check_deprecated_field_usage:")
        for e in errors:
            print(e)
        return 1
    print("OK check_deprecated_field_usage")
    return 0


if __name__ == "__main__":
    sys.exit(main())

