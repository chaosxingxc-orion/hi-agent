#!/usr/bin/env python3
"""Check that conftest.py does not enable heuristic fallback unconditionally."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFTEST = ROOT / "tests" / "conftest.py"


def main() -> int:
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

    result = {"status": "pass" if not violations else "fail", "violations": violations}
    print(json.dumps(result, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
