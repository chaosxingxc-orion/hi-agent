#!/usr/bin/env python3
"""Check that conftest.py does not enable heuristic fallback unconditionally.

Exit 0: pass (no violations or file not present).
Exit 1: fail (violations found).
Exit 2: not_applicable (conftest.py does not exist in expected location).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFTEST = ROOT / "tests" / "conftest.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Conftest fallback scope gate.")
    parser.add_argument("--strict", action="store_true",
                        help="Treat absent input as fail rather than not_applicable")
    args = parser.parse_args()

    if not CONFTEST.exists():
        if args.strict:
            print(f"FAIL (strict): input absent at {CONFTEST}; "
                  "in strict mode, absent input is a defect", file=sys.stderr)
            return 1
        result = {
            "status": "not_applicable",
            "check": "conftest_fallback_scope",
            "reason": "tests/conftest.py not found",
            "violations": [],
        }
        print(json.dumps(result, indent=2))
        return 2

    src = CONFTEST.read_text(encoding="utf-8")
    lines = src.splitlines()
    violations = []
    for i, line in enumerate(lines, 1):
        if "HEURISTIC_FALLBACK" in line and "=" in line and "1" in line:
            # Check if there's an if statement within 3 lines before
            context = lines[max(0, i - 4) : i - 1]
            if not any("if " in c for c in context):
                violations.append(
                    f"Line {i}: HEURISTIC_FALLBACK set without conditional guard"
                )

    status = "pass" if not violations else "fail"
    result = {
        "status": status,
        "check": "conftest_fallback_scope",
        "violations": violations,
    }
    print(json.dumps(result, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
