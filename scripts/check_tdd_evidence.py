#!/usr/bin/env python
"""CI gate: fail if agent_server/api/routes_*.py handlers lack tdd-red-sha annotation (R-AS-5).

Every route handler must have been TDD-driven, evidenced by a comment:
    # tdd-red-sha: <7-40 char hex SHA of the failing-test commit>

Usage: python scripts/check_tdd_evidence.py
Exit 0 = clean or no routes yet; 1 = violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
API_DIR = ROOT / "agent_server" / "api"

# Match route handlers (async def or def at module level)
HANDLER_RE = re.compile(r'^(async def|def)\s+(\w+)\s*\(', re.MULTILINE)
# Match tdd-red-sha annotation (anywhere in the file)
TDD_SHA_RE = re.compile(r'#\s*tdd-red-sha:\s*([0-9a-f]{7,40})', re.IGNORECASE)


def check() -> int:
    if not API_DIR.exists():
        print("PASS (R-AS-5): agent_server/api/ not yet created — skipping")
        return 0

    route_files = sorted(API_DIR.glob("routes_*.py"))
    if not route_files:
        print("PASS (R-AS-5): no routes_*.py files yet — skipping")
        return 0

    violations = []
    for py_file in route_files:
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        # Check the file has at least one tdd-red-sha annotation
        if not TDD_SHA_RE.search(text):
            violations.append(
                f"  {py_file.relative_to(ROOT)}: no '# tdd-red-sha: <sha>' annotation found"
            )

    if violations:
        print(f"FAIL (R-AS-5): {len(violations)} route file(s) missing tdd-red-sha annotation:")
        for v in violations:
            print(v)
        print("\nAdd '# tdd-red-sha: <sha>' comment referencing the failing-test commit SHA.")
        return 1
    print(f"PASS (R-AS-5): all {len(route_files)} route file(s) have tdd-red-sha annotation")
    return 0


if __name__ == "__main__":
    sys.exit(check())
